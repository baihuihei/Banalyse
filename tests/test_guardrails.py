"""红线守卫测试（禁止交易买卖建议词汇扫描与清洗）。"""
from banalyse.agents.guardrails import (
    DISCLAIMER,
    find_advice_terms,
    strip_advice_lines,
    with_disclaimer,
)


class TestGuardrails:
    def test_find_advice_terms_chinese(self):
        text = "当前基本面良好，请勿买入，目标价设为100元，切勿清仓。"
        terms = find_advice_terms(text)
        assert "买入" in terms
        assert "目标价" in terms
        assert "清仓" in terms

    def test_find_advice_terms_greedy_phrase(self):
        text = "机构建议买入，给予买入建议。"
        terms = find_advice_terms(text)
        assert "建议买" in terms or "买入" in terms

    def test_find_advice_terms_english(self):
        text = "We recommend a BUY rating and set a price target of $150. Do not hold."
        terms = [t.lower() for t in find_advice_terms(text)]
        assert "buy" in terms
        assert "price target" in terms
        assert "hold" in terms

    def test_clean_text_no_advice(self):
        text = "企业长期毛利率维持在60%以上，具有较强的定价权和品牌护城河。"
        assert find_advice_terms(text) == []

    def test_strip_advice_lines(self):
        text = (
            "第一行：商业模式清晰稳定。\n"
            "第二行：建议强烈买入该标的。\n"
            "第三行：现金流充沛且负债率低。"
        )
        cleaned = strip_advice_lines(text)
        assert "买入" not in cleaned
        assert "商业模式清晰稳定" in cleaned
        assert "现金流充沛且负债率低" in cleaned

    def test_with_disclaimer(self):
        raw = "企业综合分析报告正文。"
        res = with_disclaimer(raw)
        assert DISCLAIMER in res
        # 幂等性：重复添加不会变多
        assert with_disclaimer(res) == res
