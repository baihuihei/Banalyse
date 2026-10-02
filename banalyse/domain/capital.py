"""确定性资本回报指标：ROE（含杜邦拆分）、ROIC、自由现金流、资本开支强度。

为什么放在这里而不是交给 LLM
----------------------------
这些都是**可复算的算术**，交给语言模型必然出现数字幻觉。
智能体只能引用本模块的输出（「资本回报」维度的证据来源）。

输入约定（字段为**按年份升序**的列表，或单年标量）
------------------------------------------------
    revenue, gross_profit, operating_income, net_income,
    shareholders_equity, total_assets, total_debt, cash,
    operating_cash_flow, depreciation_amortization, capital_expenditure,
    dividends_paid, tax_rate

缺字段不报错，只记入 ``data_gaps``——宁可承认不知道，也不臆造。
"""
from statistics import mean

# 中国企业所得税法定税率，仅作 NOPAT 的缺省假设
DEFAULT_TAX_RATE = 0.25

# 维持性资本开支无法从财报直接取得，退化为「全部资本开支」这一**保守**代理
CAPEX_PROXY_NOTE = "以全部资本开支近似维持性资本开支（保守口径，可能低估股东盈余）"

_ALIASES = {
    "revenue": ("revenue", "total_revenue", "营业收入"),
    "gross_profit": ("gross_profit", "gross_profit_loss", "毛利润"),
    "operating_income": ("operating_income", "ebit", "营业利润"),
    "net_income": ("net_income", "net_profit", "净利润"),
    "shareholders_equity": ("shareholders_equity", "total_equity", "stockholders_equity", "净资产"),
    "total_assets": ("total_assets", "assets", "总资产"),
    "total_debt": ("total_debt", "interest_bearing_debt", "有息负债"),
    "cash": ("cash", "cash_and_equivalents", "货币资金"),
    "operating_cash_flow": ("operating_cash_flow", "ocf", "经营活动现金流"),
    "depreciation_amortization": ("depreciation_amortization", "depreciation", "折旧摊销"),
    "capital_expenditure": ("capital_expenditure", "capex", "资本开支"),
    "dividends_paid": ("dividends_paid", "cash_dividends", "分红"),
}


def _num(value):
    """宽松转 float；不可转则 None（不抛异常）。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series(financials: dict, field: str) -> list[float]:
    """按别名取某字段的年度序列（升序）；标量视为单年。"""
    for name in _ALIASES.get(field, (field,)):
        if name not in financials:
            continue
        raw = financials[name]
        if isinstance(raw, (list, tuple)):
            return [v for v in (_num(x) for x in raw) if v is not None]
        number = _num(raw)
        return [number] if number is not None else []
    return []


def _latest(series: list[float]):
    return series[-1] if series else None


def _round(value, digits: int = 4):
    return None if value is None else round(value, digits)


def _trend(series: list[float]) -> str:
    """首尾比较给出趋势；不足两年返回 unknown。"""
    if len(series) < 2:
        return "unknown"
    delta = series[-1] - series[0]
    scale = abs(series[0]) or 1.0
    if delta / scale > 0.05:
        return "rising"
    if delta / scale < -0.05:
        return "falling"
    return "stable"


def _average_equity(equity: list[float], index: int):
    """优先用平均净资产（更稳健）；没有上年数据则用期末。"""
    if index > 0:
        return (equity[index] + equity[index - 1]) / 2
    return equity[index]
def compute_roe(financials: dict) -> dict:
    """净资产收益率 + 杜邦拆分（看清高 ROE 是来自盈利、效率，还是加杠杆）。"""
    net_income = _series(financials, "net_income")
    equity = _series(financials, "shareholders_equity")
    if not net_income or not equity:
        return {"available": False, "reason": "缺少净利润或净资产"}

    roes: list[float] = []
    n = min(len(net_income), len(equity))
    for i in range(n):
        base = _average_equity(equity, i)
        if base in (None, 0):
            continue
        roes.append(net_income[i] / base)
    if not roes:
        return {"available": False, "reason": "净资产为 0，无法计算"}

    result = {
        "available": True,
        "series": [_round(r) for r in roes],
        "latest": _round(roes[-1]),
        "trend": _trend(roes),
        "years": len(roes),
        # 「持续多年」是重点：全为正 且 最低值不低于均值的一半
        "consistent": all(r > 0 for r in roes) and min(roes) >= 0.5 * mean(roes),
    }

    # 杜邦拆分需要同期收入与总资产；缺则只给 ROE 不做拆分（不臆造）
    revenue = _series(financials, "revenue")
    assets = _series(financials, "total_assets")
    if revenue and assets:
        m = min(len(revenue), len(assets), len(net_income), len(equity))
        idx = m - 1
        eq = _average_equity(equity, idx)
        if eq and revenue[idx] and assets[idx]:
            net_margin = net_income[idx] / revenue[idx]
            asset_turnover = revenue[idx] / assets[idx]
            equity_multiplier = assets[idx] / eq
            result["dupont"] = {
                "net_margin": _round(net_margin),
                "asset_turnover": _round(asset_turnover),
                "equity_multiplier": _round(equity_multiplier),
                # 三者相乘应还原 ROE，用于自检
                "product": _round(net_margin * asset_turnover * equity_multiplier),
                "leverage_driven": equity_multiplier >= 2.0,
            }
    else:
        result["dupont"] = None
        result.setdefault("data_gaps", []).append("缺少营业收入或总资产，无法做杜邦拆分")
    return result


def compute_roic(financials: dict, wacc: float | None = None) -> dict:
    """投入资本回报率 = NOPAT / 投入资本；剔除杠杆干扰，判断是否真正创造价值。

    投入资本 = 股东权益 + 有息负债 − 现金（巴菲特式口径：只算经营性占用资本）。
    """
    operating_income = _latest(_series(financials, "operating_income"))
    if operating_income is None:
        return {"available": False, "reason": "缺少营业利润（EBIT），无法计算 NOPAT"}

    equity = _latest(_series(financials, "shareholders_equity"))
    debt = _latest(_series(financials, "total_debt")) or 0.0
    cash = _latest(_series(financials, "cash")) or 0.0
    tax_rate = _num(financials.get("tax_rate"))
    if tax_rate is None:
        tax_rate = DEFAULT_TAX_RATE

    if equity is None:
        return {"available": False, "reason": "缺少股东权益，无法计算投入资本"}

    invested_capital = equity + debt - cash
    if invested_capital <= 0:
        return {
            "available": False,
            "reason": f"投入资本为 {invested_capital:.0f}（≤0），多见于现金极多的公司，ROIC 不适用",
        }

    nopat = operating_income * (1 - tax_rate)
    roic = nopat / invested_capital
    result = {
        "available": True,
        "nopat": _round(nopat),
        "invested_capital": _round(invested_capital),
        "roic": _round(roic),
        "tax_rate_used": _round(tax_rate),
        "inputs": {"ebit": _round(operating_income), "equity": _round(equity),
                   "debt": _round(debt), "cash": _round(cash)},
        "note": "投入资本 = 股东权益 + 有息负债 − 现金；税率未提供时按 25% 假设",
    }
    if wacc is not None:
        result["wacc"] = _round(float(wacc))
        result["excess_return"] = _round(roic - float(wacc))
        result["creates_value"] = roic > float(wacc)
    return result
def compute_free_cash_flow(financials: dict) -> dict:
    """自由现金流 = 经营现金流 − 资本开支；并给出 FCF / 净利润，检验利润质量。"""
    ocf = _latest(_series(financials, "operating_cash_flow"))
    if ocf is None:
        return {"available": False, "reason": "缺少经营活动现金流"}

    capex = _latest(_series(financials, "capital_expenditure")) or 0.0
    fcf = ocf - abs(capex)
    net_income = _latest(_series(financials, "net_income"))

    result = {
        "available": True,
        "operating_cash_flow": _round(ocf),
        "capital_expenditure": _round(abs(capex)),
        "fcf": _round(fcf),
        "note": "自由现金流 = 经营现金流 − 资本开支",
    }
    if net_income not in (None, 0):
        result["net_income"] = _round(net_income)
        result["fcf_to_net_income"] = _round(fcf / net_income)
        # 长期显著低于 1 说明利润没有变成现金（应收挂账 / 重资产扩张）
        result["cash_backed"] = fcf / net_income >= 0.8
    else:
        result["fcf_to_net_income"] = None
        result.setdefault("data_gaps", []).append("缺少净利润，无法评估利润的现金含量")
    return result


def compute_margins(financials: dict) -> dict:
    """毛利率 / 营业利润率 / 净利率及趋势（判断定价权与成本管控）。"""
    revenue = _series(financials, "revenue")
    if not revenue:
        return {"available": False, "reason": "缺少营业收入"}

    def ratio_series(numerator_field: str) -> list[float]:
        numerator = _series(financials, numerator_field)
        n = min(len(numerator), len(revenue))
        return [
            numerator[i] / revenue[i]
            for i in range(n)
            if revenue[i] not in (None, 0)
        ]

    out: dict = {"available": True}
    for name, field in (("gross", "gross_profit"), ("operating", "operating_income"), ("net", "net_income")):
        series = ratio_series(field)
        out[name] = {
            "latest": _round(series[-1]) if series else None,
            "trend": _trend(series),
        }
    return out


def compute_capex_intensity(financials: dict) -> dict:
    """资本开支强度 = 资本开支 / 营业收入，判断是维持性还是扩张性投入。"""
    revenue = _series(financials, "revenue")
    capex = _series(financials, "capital_expenditure")
    if not revenue or not capex:
        return {"available": False, "reason": "缺少营业收入或资本开支"}

    n = min(len(revenue), len(capex))
    ratios = [
        abs(capex[i]) / revenue[i]
        for i in range(n)
        if revenue[i] not in (None, 0)
    ]
    if not ratios:
        return {"available": False, "reason": "营业收入为 0，无法计算资本开支强度"}
    return {
        "available": True,
        "latest": _round(ratios[-1]),
        "trend": _trend(ratios),
        "note": "资本开支强度上升通常意味着扩张期，但若 ROIC 未同步改善则是低效投入",
    }


def compute_capital_metrics(financials: dict, wacc: float | None = None) -> dict:
    """汇总「资本回报」维度全部确定性计算；缺项如实记入 data_gaps。"""
    financials = financials or {}
    blocks = {
        "roe": compute_roe(financials),
        "roic": compute_roic(financials, wacc=wacc),
        "free_cash_flow": compute_free_cash_flow(financials),
        "margins": compute_margins(financials),
        "capex_intensity": compute_capex_intensity(financials),
    }
    gaps: list[str] = []
    for name, block in blocks.items():
        if not block.get("available") and block.get("reason"):
            gaps.append(f"{name}: {block['reason']}")
        gaps.extend(block.get("data_gaps") or [])

    return {
        "available": any(b.get("available") for b in blocks.values()),
        "metrics": blocks,
        "data_gaps": gaps,
        "note": "以上数字由确定性代码计算，任何智能体只能引用，不得改动或自行重算。",
    }
