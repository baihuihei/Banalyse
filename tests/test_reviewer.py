"""汇总节点 + 自由文本解析测试。

重点是：**不依赖 provider 的结构化输出**，模型只要正常写 Markdown 小标题，
就能切回展示字段；写不出来也不能失败。
"""
from banalyse.agents.base import EMPTY_REPLY, content_to_text, invoke_text
from banalyse.agents.guardrails import DISCLAIMER
from banalyse.agents.reviewer import create_reviewer, split_sections


class FakeReply:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """按调用次序依次返回预设内容（不足则重复最后一个）。"""

    def __init__(self, *contents):
        self._contents = list(contents)
        self.calls = 0

    def invoke(self, messages):
        content = self._contents[min(self.calls, len(self._contents) - 1)]
        self.calls += 1
        if isinstance(content, Exception):
            raise content
        return FakeReply(content)


FULL_REPORT = """## 综合结论
公司整体呈现"高回报、低净资产"的特征，需关注回购对账面权益的持续压缩。

## 报告正文
这里是完整的分析正文，包含四个维度的合并叙述与数据缺口说明。
"""


def _state():
    return {"ticker": "AAPL", "company_name": "Apple", "report_date": "2026-09-01",
            "reports": {}, "capital": {}, "valuation": {}, "evidence": {}}


class TestSplitSections:
    def test_conclusion_and_document_are_separated(self):
        out = split_sections(FULL_REPORT)
        assert "高回报、低净资产" in out["conclusion"]
        assert "完整的分析正文" in out["document"]

    def test_conclusion_excludes_the_body(self):
        assert "完整的分析正文" not in split_sections(FULL_REPORT)["conclusion"]

    def test_audit_fields_are_gone(self):
        """交叉校验与来源标记已删除 —— 这三个字段不该再冒出来。"""
        out = split_sections(FULL_REPORT)
        assert set(out) == {"conclusion", "document"}

    def test_no_headings_degrades_to_whole_document(self):
        """模型没写标题时应退化成"整篇都是正文"，而不是解析失败。"""
        out = split_sections("一段没有小标题的分析文字。\n\n第二段。")
        assert out["document"].startswith("一段没有小标题")
        assert out["conclusion"] == "一段没有小标题的分析文字。"

    def test_unknown_headings_go_into_document(self):
        out = split_sections("## 其他说明\n这部分不该丢。\n\n## 综合结论\n结论在此。")
        assert "这部分不该丢" in out["document"]
        assert out["conclusion"] == "结论在此。"

    def test_body_heading_variant_is_recognised(self):
        assert split_sections("### 正文\n正文内容")["document"] == "正文内容"

    def test_empty_input_is_safe(self):
        out = split_sections("")
        assert out["document"] == "" and out["conclusion"] == ""


class TestInvokeText:
    def test_returns_content(self):
        assert invoke_text(FakeLLM("分析结果"), "prompt", "t") == "分析结果"

    def test_retries_on_empty_content(self):
        """推理型模型会返回 content=None；必须重试而不是把空串传下去。"""
        assert invoke_text(FakeLLM(None, "第二次有内容"), "prompt", "t") == "第二次有内容"

    def test_explicit_marker_when_still_empty(self):
        assert invoke_text(FakeLLM(None), "prompt", "t") == EMPTY_REPLY

    def test_provider_exception_becomes_visible_text(self):
        out = invoke_text(FakeLLM(RuntimeError("boom")), "prompt", "t")
        assert "RuntimeError" in out and "boom" in out

    def test_whitespace_only_counts_as_empty(self):
        assert invoke_text(FakeLLM("   \n  "), "prompt", "t") == EMPTY_REPLY


class TestContentToText:
    def test_none_and_empty(self):
        assert content_to_text(None) == ""
        assert content_to_text("") == ""

    def test_plain_string_is_stripped(self):
        assert content_to_text("  hi  ") == "hi"

    def test_block_list_is_joined(self):
        blocks = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        assert content_to_text(blocks) == "a\nb"

    def test_non_text_blocks_are_ignored(self):
        blocks = [{"type": "text", "text": "a"}, {"type": "image_url", "image_url": {}}]
        assert content_to_text(blocks) == "a"


class TestReviewerNode:
    def test_free_text_is_split_and_disclaimed(self):
        out = create_reviewer(FakeLLM(FULL_REPORT), "Chinese")(_state())
        review = out["review"]
        assert review["conclusion"]
        assert "完整的分析正文" in review["document"]
        assert DISCLAIMER in review["document"]
        assert review["guardrail"]["retries"] == 0
        assert out["trace"] == ["reviewer"]

    def test_review_carries_no_audit_fields(self):
        """产出只剩：综合结论 / 正文 / 声明 / 守门状态。"""
        out = create_reviewer(FakeLLM(FULL_REPORT), "Chinese")(_state())
        assert set(out["review"]) == {"conclusion", "document", "disclaimer", "guardrail"}

    def test_plain_prose_still_yields_a_conclusion(self, mock_deep_llm):
        """mock 模型不写小标题 —— 这种情况也必须给出可展示的结论。"""
        out = create_reviewer(mock_deep_llm, "Chinese")(_state())
        assert out["review"]["conclusion"].strip()
        assert out["review"]["document"].strip()

    def test_out_of_bounds_wording_triggers_one_rewrite(self):
        node = create_reviewer(FakeLLM("## 综合结论\n建议买入，目标价 200 元。", FULL_REPORT),
                               "Chinese")
        out = node(_state())
        assert out["review"]["guardrail"]["retries"] == 1
        assert out["review"]["guardrail"]["stripped"] is False

    def test_persistent_violation_is_stripped_not_fatal(self):
        node = create_reviewer(FakeLLM("## 综合结论\n建议买入。\n合规的一段分析文字。"), "Chinese")
        out = node(_state())
        assert out["review"]["guardrail"]["stripped"] is True
        assert "买入" not in out["review"]["document"]
        assert "合规的一段分析文字" in out["review"]["document"]

    def test_empty_model_reply_is_marked_explicitly(self):
        out = create_reviewer(FakeLLM(None), "Chinese")(_state())
        assert EMPTY_REPLY in out["review"]["document"]


class TestReviewPromptShape:
    def test_prompt_requests_markdown_headings_not_json(self):
        from banalyse.agents.reviewer import build_review_prompt
        text = str(build_review_prompt(_state(), "Chinese").invoke({}))
        assert "## 综合结论" in text
        assert "## 报告正文" in text
        assert "不要输出 JSON" in text

    def test_prompt_no_longer_asks_for_cross_checking_or_sources(self):
        """两个功能已删除：prompt 里不该再要求交叉校验 / 来源标记。"""
        from banalyse.agents.reviewer import build_review_prompt
        text = str(build_review_prompt(_state(), "Chinese").invoke({}))
        for gone in ("交叉校验", "交叉印证", "来源标记", "SOURCE_TAXONOMY",
                     "cross_checks", "conflicts", "source_notes"):
            assert gone not in text, f"{gone} 应从 prompt 中移除"

    def test_four_dimension_reports_are_still_the_input(self):
        """合并职责保留：四份维度报告仍然要进 prompt。"""
        from banalyse.agents.dimensions import DIMENSION_ORDER, get_dimension
        from banalyse.agents.reviewer import build_review_prompt
        state = _state()
        state["reports"] = {key: f"{key} 的分析内容" for key in DIMENSION_ORDER}
        text = str(build_review_prompt(state, "Chinese").invoke({}))
        for key in DIMENSION_ORDER:
            assert get_dimension(key).label in text
            assert f"{key} 的分析内容" in text

    def test_prompt_does_not_enumerate_banned_words(self):
        """列举禁用词会让模型"复述禁令"，然后被 guardrails 误判成违规。"""
        from banalyse.agents.prompts import NO_ADVICE_RULE
        for term in ("买入", "卖出", "持有", "增持", "减持", "评级", "目标价", "止损", "止盈"):
            assert term not in NO_ADVICE_RULE, f"{term} 不应出现在 prompt 里"
        assert "绝不判断买还是卖" in NO_ADVICE_RULE
