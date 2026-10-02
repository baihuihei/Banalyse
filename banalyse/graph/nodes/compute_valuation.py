"""前置确定性节点：三情景 DCF 估值 + 敏感性 + 安全边际。

折现率优先以**该市场的长期国债收益率**为无风险基准（A 股/港股 → 中国国债，
美股 → 美国国债），抓不到才退回配置里写死的假设 —— 用的是哪一套会写进
``valuation['discount_basis']``，方便核对与引用。
现金流基数不可得时只产出「不可估值」的说明，不臆造任何数字。
"""
from ...domain.valuation import compute_valuation
from ...runtime_config import get_config


def _quote_inputs(state: dict) -> tuple:
    """从 evidence['quote'] 取现价与总股本；缺失返回 (None, None)。"""
    evidence = state.get("evidence") or {}
    quote = evidence.get("quote")
    if not isinstance(quote, dict):
        return None, None
    price = quote.get("price") or quote.get("close") or quote.get("现价")
    shares = quote.get("shares") or quote.get("total_shares") or quote.get("总股本")
    return price, shares


def _risk_free_input(state: dict) -> dict | None:
    """从 evidence['macro_indicators'] 取无风险利率；哨兵字符串一律视为没取到。"""
    macro = (state.get("evidence") or {}).get("macro_indicators")
    return macro if isinstance(macro, dict) else None


def make():
    """返回 node(state)：把 state['capital'] 换算成 state['valuation']。"""

    def node(state):
        cfg = get_config()
        price, shares = _quote_inputs(state)
        risk_free = _risk_free_input(state)

        valuation = compute_valuation(
            capital_metrics=state.get("capital") or {},
            price=price,
            shares=shares,
            # 拿到国债收益率时不传基础情景，让折现率按市场锚定；
            # 拿不到才用配置里的假设值。
            scenarios=None if risk_free else cfg.get("valuation_scenarios"),
            years=cfg.get("valuation_years"),
            required_margin=cfg.get("required_margin_of_safety"),
            sensitivity=cfg.get("valuation_sensitivity"),
            risk_free=risk_free,
            discount_policy=cfg.get("valuation_discount"),
        )
        return {"valuation": valuation, "trace": ["compute_valuation"]}

    return node
