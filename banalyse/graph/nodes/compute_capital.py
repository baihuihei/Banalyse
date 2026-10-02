"""前置确定性节点：计算「资本回报」维度的全部指标。

数字在这里算出来，之后所有智能体只能引用。财务数据缺失时产出一份
「全员数据缺口」的结果，让智能体如实说明而不是编造。
"""
from ...domain.capital import compute_capital_metrics
from ...runtime_config import get_config


def _as_mapping(value) -> dict:
    """只接受真正的映射；哨兵字符串 / None 一律视为无数据。"""
    return value if isinstance(value, dict) else {}


def make():
    """返回 node(state)：把 evidence['financials'] 换算成 state['capital']。"""

    def node(state):
        cfg = get_config()
        # WACC 作为 ROIC 的比较基准；缺省时退用基准情景折现率
        assumptions = cfg.get("valuation_assumptions") or {}
        scenarios = cfg.get("valuation_scenarios") or {}
        wacc = assumptions.get("wacc") or (scenarios.get("base") or {}).get("discount_rate")

        evidence = state.get("evidence") or {}
        financials = _as_mapping(evidence.get("financials"))

        metrics = compute_capital_metrics(financials, wacc=wacc)
        if not financials:
            metrics.setdefault("data_gaps", []).append(
                "财报数据不可用（供应商未实现或返回哨兵），资本回报指标均无法计算"
            )
        metrics["inputs_available"] = bool(financials)
        return {"capital": metrics, "trace": ["compute_capital"]}

    return node
