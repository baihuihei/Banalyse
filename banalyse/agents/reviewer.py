"""汇总智能体：把四份维度报告合并成一份完整研究（仍不判断买还是卖）。

**只做合并。** 原先还有两项审计职责 —— 交叉校验（维度间结论是否互相印证 / 冲突）
与来源标记（每条结论标注来自 10-K / DEF 14A / 系统计算 / 模型推断）—— 已按要求移除。
所以本节点不再产出 ``cross_checks`` / ``conflicts`` / ``source_notes``，
只产出 ``conclusion``（综合结论）与 ``document``（完整报告正文）。

保留的两道防线都不靠 prompt，而是机械兜底：
  · 边界扫描（``guardrails``）—— 命中交易建议类措辞就重写，再退化为剥离；
  · 材料缺口如实列出（``render_evidence_gaps``）—— 让模型知道哪些输入本来就是空的，
    而不是把"没有材料"当成"没有风险"。

输出不做 schema 约束：模型只需正常写 Markdown 小标题，再由 :func:`split_sections`
切出综合结论与正文。切不出来也不会失败，只会退化成"整篇都是正文"。
"""
import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from .base import invoke_text
from .context import get_language_instruction, instrument_context
from .data_block import build_data_block
from .dimensions import DIMENSION_ORDER, EVIDENCE_LABELS, get_dimension
from .guardrails import (
    DISCLAIMER,
    RETRY_INSTRUCTION,
    find_advice_terms,
    strip_advice_lines,
    with_disclaimer,
)
from .prompts import ANALYSIS_FRAMEWORK, EVIDENCE_DISCIPLINE, NO_ADVICE_RULE

logger = logging.getLogger(__name__)

SYSTEM_ROLE = (
    "你是这份研究的汇总分析师。把四个维度的报告合并成一份完整、连贯的研究文档："
    "保持各维度的结论原样，不要引入新的数据或判断，也不要把四份报告简单堆叠了事。"
)


def render_reports(state: dict) -> str:
    """把四个维度的报告按固定顺序渲染；缺失的维度如实标注。"""
    reports = state.get("reports") or {}
    chunks: list[str] = []
    for key in DIMENSION_ORDER:
        dimension = get_dimension(key)
        text = (reports.get(key) or "").strip()
        if not text:
            # 该维度未产出（重试用尽）：显式记入，避免报告看起来"什么都好"
            text = "（该维度报告缺失：分析师未能产出有效内容，请在结论中标注此局限）"
        chunks.append(f"### {dimension.label}\n{text}")
    return "\n\n".join(chunks)


def render_computed(state: dict) -> str:
    """确定性计算结果（财务指标 + 估值），供校验时核对数字。"""
    return "\n\n".join(
        [
            build_data_block(state.get("capital") or {}, title="财务指标（系统计算）"),
            build_data_block(state.get("valuation") or {}, title="估值结果（系统计算）"),
        ]
    )


def render_evidence_gaps(state: dict) -> str:
    """列出哪些原始材料其实没拿到，避免汇总层把"无材料"当成"无风险"。"""
    evidence = state.get("evidence") or {}
    missing = [
        EVIDENCE_LABELS.get(slot, slot)
        for slot, value in evidence.items()
        if not isinstance(value, dict) and not str(value or "").strip()
    ]
    if not missing:
        return "(材料槽位均有内容)"
    return "以下材料未取到，相关结论只能标注为数据不足：" + "、".join(missing)
def build_review_prompt(
    state: dict, language: str = "Chinese", extra_instruction: str = ""
) -> ChatPromptTemplate:
    """构造汇总 prompt（拆出来便于单测）。"""
    system = "\n\n".join(
        [
            SYSTEM_ROLE,
            ANALYSIS_FRAMEWORK,
            EVIDENCE_DISCIPLINE,
            NO_ADVICE_RULE,
            "输出用 Markdown 小标题分节，且只使用这两个标题："
            "『## 综合结论』『## 报告正文』。不要输出 JSON。",
        ]
    ) + get_language_instruction(language)

    human = "\n\n".join(
        [
            instrument_context(state),
            f"分析基准日：{state.get('report_date', '')}",
            f"## 四个维度的分析报告\n{render_reports(state)}",
            f"## 确定性计算结果（只能引用，不得改动）\n{render_computed(state)}",
            f"## 材料完备性\n{render_evidence_gaps(state)}",
            "请把以上内容合并成一份完整的分析报告。",
        ]
    ) + extra_instruction

    return ChatPromptTemplate.from_messages([("system", system), ("human", human)])


# ---------------------------------------------------------------- 自由文本 → 展示字段
# 不依赖 provider 的结构化输出，按 Markdown 标题切 —— 模型只要正常写小标题即可。
SECTION_LABELS: dict[str, str] = {
    "综合结论": "conclusion",
    "报告正文": "document",
    "正文": "document",
}

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*#*\s*$")


def _heading_key(title: str) -> str | None:
    """把小标题映射到展示字段；认不出的返回 None（内容归入正文）。"""
    cleaned = title.strip().strip("：: 　【】[]")
    for label, key in SECTION_LABELS.items():
        if label in cleaned:
            return key
    return None


def _first_paragraph(text: str) -> str:
    for paragraph in (text or "").split("\n\n"):
        if paragraph.strip():
            return paragraph.strip()
    return ""


def split_sections(text: str) -> dict:
    """按 Markdown 标题切出「综合结论」与「报告正文」。

    容错优先：认不出的标题（以及没写标题的整篇文字）全部并入 ``document``，
    所以这个函数永远不会失败；``conclusion`` 拿不到就退化为正文首段。
    """
    buckets: dict[str, list[str]] = {}
    current = "document"
    pending: list[str] = []

    def flush():
        if pending:
            buckets.setdefault(current, []).extend(pending)
            pending.clear()

    for line in (text or "").splitlines():
        match = _HEADING.match(line)
        key = _heading_key(match.group(1)) if match else None
        if key:
            flush()
            current = key
            continue
        pending.append(line)
    flush()

    document = "\n".join(buckets.get("document", [])).strip() or (text or "").strip()
    conclusion = "\n".join(buckets.get("conclusion", [])).strip()
    return {
        "conclusion": conclusion or _first_paragraph(document),
        "document": document,
    }


def create_reviewer(llm, language: str = "Chinese", max_retries: int = 1):
    """返回汇总节点。``max_retries`` 控制因越界措辞而重写的次数。"""

    def node(state):
        text = invoke_text(llm, build_review_prompt(state, language), "reviewer")

        # 边界兜底：命中交易建议类措辞 → 带指令重写
        attempts = 0
        for _ in range(max_retries):
            flagged = find_advice_terms(text)
            if not flagged:
                break
            attempts += 1
            logger.warning("reviewer: advice terms detected %s; retrying", flagged)
            text = invoke_text(
                llm, build_review_prompt(state, language, RETRY_INSTRUCTION), "reviewer"
            )

        flagged = find_advice_terms(text)
        stripped = False
        if flagged:
            # 仍命中：剥离相关整行并记录，绝不中断流水线
            logger.warning("reviewer: advice terms persisted %s; stripping", flagged)
            text = strip_advice_lines(text)
            stripped = True

        sections = split_sections(text)
        return {
            "review": {
                "conclusion": sections["conclusion"],
                "document": with_disclaimer(sections["document"]),
                "disclaimer": DISCLAIMER,
                "guardrail": {
                    "retries": attempts,
                    "flagged_terms": flagged,
                    "stripped": stripped,
                },
            },
            "trace": ["reviewer"],
        }

    return node
