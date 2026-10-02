"""Supervisor 多智能体图冒烟测试：离线（mock LLM）端到端运行验证。"""
import json

import pytest

from banalyse.agents.dimensions import DIMENSION_ORDER
from banalyse.default_config import DEFAULT_CONFIG
from banalyse.graph.builder import build_graph
from banalyse.graph.state import reduce_merge
from banalyse.graph.workflow import BanalyseGraph


def _config(tmp_path, **overrides):
    cfg = {**DEFAULT_CONFIG, "llm_provider": "mock", "results_dir": str(tmp_path)}
    cfg.update(overrides)
    return cfg


class TestGraphCompile:
    def test_graph_compiles(self, mock_llm, mock_deep_llm):
        assert build_graph(mock_llm, mock_deep_llm) is not None

    def test_unknown_dimension_rejected_early(self, mock_llm, mock_deep_llm):
        with pytest.raises(ValueError):
            build_graph(mock_llm, mock_deep_llm, {"dimensions": ["not-a-dimension"]})


class TestEndToEnd:
    def test_full_pipeline_runs_offline(self, tmp_path, offline_evidence):
        state = BanalyseGraph(config=_config(tmp_path)).analyze(
            "600519.SS", "贵州茅台", "2026-09-01"
        )
        trace = state["trace"]

        # 前置确定性节点先跑，汇总打包收尾
        assert trace[0] == "collect_evidence"
        assert trace[1] == "compute_capital"
        assert trace[2] == "compute_valuation"
        assert trace[-1] == "assemble"

        # 四位分析师各被派活一次，且都产出了非空报告
        for key in DIMENSION_ORDER:
            assert f"supervisor→{key} (#1)" in trace
            assert f"analyst:{key}" in trace
            assert (state["reports"].get(key) or "").strip()

        final = state["final_report"]
        assert final["conclusion"].strip()
        assert final["markdown"].strip()
        assert set(final["reports"]) == set(DIMENSION_ORDER)
        assert state["result_path"].endswith(".json")

    def test_report_is_written_to_disk(self, tmp_path, offline_evidence):
        state = BanalyseGraph(config=_config(tmp_path)).analyze("AAPL", "Apple", "2026-09-01")
        with open(state["result_path"], encoding="utf-8") as fh:
            payload = json.load(fh)
        assert payload["company"]["ticker"] == "AAPL"
        assert set(payload["reports"]) == set(DIMENSION_ORDER)
        assert payload["disclaimer"]
        assert payload["trace"]

    def test_subset_dimensions_only_runs_those(self, tmp_path, offline_evidence):
        cfg = _config(tmp_path, dimensions=["business_model", "capital_return"])
        state = BanalyseGraph(config=cfg).analyze("AAPL", "Apple", "2026-09-01")
        assert set(state["reports"]) == {"business_model", "capital_return"}
        assert "analyst:management" not in state["trace"]

    def test_offline_run_self_annotates_missing_data(self, tmp_path, offline_evidence):
        """M0 无供应商实现 → 材料全是哨兵，报告必须如实说明而非编造。"""
        state = BanalyseGraph(config=_config(tmp_path)).analyze("AAPL", "Apple", "2026-09-01")
        evidence = state["evidence"]
        assert evidence["_meta"]["ticker"] == "AAPL"
        for slot in ("profile", "financials", "news"):
            text = str(evidence.get(slot) or "")
            assert "NO_DATA_AVAILABLE" in text or "DATA_UNAVAILABLE" in text
        # 财务数据缺失 → 资本回报指标明确记为不可计算
        assert state["capital"]["inputs_available"] is False
        assert state["capital"]["data_gaps"]

    def test_guardrail_metadata_is_recorded(self, tmp_path, offline_evidence):
        state = BanalyseGraph(config=_config(tmp_path)).analyze("AAPL", "Apple", "2026-09-01")
        guardrail = state["final_report"]["guardrail"]
        assert set(guardrail) == {"retries", "flagged_terms", "stripped"}


class TestStateReducer:
    def test_reports_merge_across_analysts(self):
        merged = reduce_merge({"business_model": "a"}, {"management": "b"})
        assert merged == {"business_model": "a", "management": "b"}
        # 不同键互不影响
        assert reduce_merge(merged, {"capital_return": "c"}) == {
            "business_model": "a", "management": "b", "capital_return": "c",
        }
        # 同键：后者覆盖（重派时刷新该维度）
        assert reduce_merge({"business_model": "a"}, {"business_model": "x"})["business_model"] == "x"

    def test_reducer_tolerates_none(self):
        assert reduce_merge(None, {"a": "1"}) == {"a": "1"}
        assert reduce_merge({"a": "1"}, None) == {"a": "1"}

