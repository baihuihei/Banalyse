"""四维度分析师工厂、判读准则与输入拼装测试。"""
import pytest

from banalyse.agents.analysts import (
    analyst_node_names,
    build_analyst_prompt,
    build_inputs,
    create_analyst,
)
from banalyse.agents.dimensions import (
    DIMENSION_ORDER,
    DIMENSIONS,
    dimension_keys,
    get_dimension,
    render_criteria,
)


class TestDimensionRegistry:
    def test_four_dimensions_defined(self):
        assert set(DIMENSIONS) == {
            "business_model",
            "management",
            "capital_return",
            "margin_of_safety",
        }
        assert set(dimension_keys()) == set(DIMENSION_ORDER)

    def test_supervisor_order_is_fixed(self):
        assert DIMENSION_ORDER == (
            "business_model",
            "management",
            "capital_return",
            "margin_of_safety",
        )

    def test_every_dimension_declares_role_criteria_and_inputs(self):
        for key, dim in DIMENSIONS.items():
            assert dim.key == key
            assert dim.label.strip()
            assert dim.role.strip()
            # 判读要点条数由各维度自己定（商业模式 3 条，其余各 5 条），
            # 这里只保证“够用且成体系”，不写死具体数字
            assert len(dim.criteria) >= 3
            # 每个维度至少要消费一份材料或一项确定性计算结果
            assert dim.evidence or dim.computed

    def test_capital_and_valuation_are_computed_not_llm_derived(self):
        # 资本回报与安全边际必须读系统计算结果，禁止 LLM 自行重算
        assert "capital" in DIMENSIONS["capital_return"].computed
        assert "valuation" in DIMENSIONS["margin_of_safety"].computed

    def test_render_criteria_numbers_each_item(self):
        text = render_criteria(get_dimension("business_model"))
        assert "1. 【赚钱方式】" in text
        assert "2. 【经营历史】" in text
        assert "3. 【相对同行的优势】" in text

    def test_unknown_dimension_raises(self):
        with pytest.raises(KeyError):
            get_dimension("not-a-dimension")


class TestBuildInputs:
    def test_missing_evidence_is_marked_not_invented(self):
        text = build_inputs({"evidence": {}, "capital": {}, "valuation": {}},
                            get_dimension("capital_return"))
        assert "(缺失)" in text

    def test_only_declared_slots_are_rendered(self):
        state = {
            "evidence": {"financials": {"revenue": [1000]}, "news": "不该出现在财务状况维度"},
            "capital": {"available": True},
            "valuation": {},
        }
        text = build_inputs(state, get_dimension("capital_return"))
        assert "财报数据" in text
        assert "不该出现在财务状况维度" not in text

    def test_computed_results_are_included_for_valuation(self):
        state = {"evidence": {}, "capital": {"roic": 0.15}, "valuation": {"available": True}}
        text = build_inputs(state, get_dimension("margin_of_safety"))
        assert "财务指标" in text
        assert "估值结果" in text


class TestAnalystPrompt:
    def _state(self):
        return {
            "company_name": "贵州茅台",
            "ticker": "600519.SS",
            "report_date": "2026-09-01",
            "evidence": {"profile": {"industry": "白酒"}},
            "capital": {},
            "valuation": {},
        }

    def test_prompt_carries_identity_and_dimension(self):
        text = str(build_analyst_prompt(self._state(), "business_model", "Chinese").invoke({}))
        assert "600519.SS" in text
        assert "贵州茅台" in text
        assert "商业模式" in text

    def test_prompt_carries_the_no_advice_boundary(self):
        text = str(build_analyst_prompt(self._state(), "business_model", "Chinese").invoke({}))
        assert "绝不判断买还是卖" in text

    def test_prompt_carries_evidence_discipline(self):
        text = str(build_analyst_prompt(self._state(), "capital_return", "Chinese").invoke({}))
        assert "证据纪律" in text


class TestAnalystNode:
    def test_node_writes_only_its_own_report(self, mock_llm):
        node = create_analyst("business_model", mock_llm, "Chinese")
        out = node({
            "company_name": "贵州茅台",
            "ticker": "600519.SS",
            "report_date": "2026-09-01",
            "evidence": {"profile": {"industry": "白酒"}},
            "capital": {},
            "valuation": {},
        })
        assert set(out["reports"]) == {"business_model"}
        assert out["reports"]["business_model"].strip()
        assert out["trace"] == ["analyst:business_model"]

    def test_unknown_dimension_raises_at_factory_time(self, mock_llm):
        with pytest.raises(KeyError):
            create_analyst("unknown_dimension", mock_llm)

    def test_node_names_match_dimensions(self):
        assert analyst_node_names() == {key: key for key in DIMENSIONS}
