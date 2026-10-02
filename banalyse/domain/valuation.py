"""确定性估值：三情景 DCF + 敏感性分析 + 安全边际（「股价安全边际」维度的证据来源）。

设计原则
--------
  · 只做数学，不做判断；折现率、增长率等假设全部来自配置（BA_* / 网页端），
    任何智能体都不得篡改或另算一个估值 —— 这是防止数字幻觉的关键。
  · 现金流基数取**自由现金流**（经营现金流 − 资本开支），近似巴菲特口径的股东盈余。
  · 安全边际不输出单点数字，而是给出**区间**：相对基准情景、相对悲观情景各一个折扣。

情景口径
--------
  悲观：不增长 + 更高折现率（要求更高的回报补偿）
  基准：温和增长
  乐观：高增长 + 更低折现率
"""
DEFAULT_SCENARIOS = {
    "pessimistic": {"discount_rate": 0.11, "growth_rate": 0.00, "terminal_growth": 0.015},
    "base": {"discount_rate": 0.09, "growth_rate": 0.05, "terminal_growth": 0.025},
    "optimistic": {"discount_rate": 0.08, "growth_rate": 0.10, "terminal_growth": 0.035},
}
SCENARIO_LABELS = {"pessimistic": "悲观", "base": "基准", "optimistic": "乐观"}

DEFAULT_YEARS = 10
DEFAULT_REQUIRED_MARGIN = 0.30
DEFAULT_SENSITIVITY = {
    "discount_rates": [0.08, 0.09, 0.10, 0.11, 0.12],
    "terminal_growths": [0.015, 0.02, 0.025, 0.03],
}

# 折现率政策：以**该市场的长期国债收益率**为无风险基准，加一段股权风险溢价，
# 三个情景再各自加减价差。抓不到国债收益率时退回 DEFAULT_SCENARIOS 里写死的费率。
DEFAULT_DISCOUNT_POLICY = {
    "equity_risk_premium": 0.05,
    "scenario_spread": {"pessimistic": 0.02, "base": 0.0, "optimistic": -0.01},
}


def anchored_scenarios(risk_free_rate: float, policy: dict | None = None,
                       base_scenarios: dict | None = None) -> dict:
    """以国债收益率为锚推出三情景折现率。

    增长率、永续增长率仍沿用基准情景设定，只有折现率随市场变化 ——
    因为「用哪国国债」影响的正是无风险利率，不该顺手改掉增长假设。
    """
    pol = {**DEFAULT_DISCOUNT_POLICY, **(policy or {})}
    anchor = float(risk_free_rate) + float(pol["equity_risk_premium"])
    spreads = pol.get("scenario_spread") or {}
    template = base_scenarios or DEFAULT_SCENARIOS

    out: dict[str, dict] = {}
    for key, assumptions in template.items():
        spread = float(spreads.get(key, 0.0))
        out[key] = {**assumptions, "discount_rate": round(anchor + spread, 6)}
    return out


def _risk_free_rate(risk_free: dict | None) -> float | None:
    """从宏观指标块里取无风险利率；结构不对或非正数一律视为没取到。"""
    if not isinstance(risk_free, dict):
        return None
    try:
        rate = float(risk_free.get("rate"))
    except (TypeError, ValueError):
        return None
    return rate if 0 < rate < 0.30 else None


def discount_basis(risk_free: dict | None, policy: dict | None = None) -> dict:
    """告诉下游「这次折现率是怎么来的」——引用时才有据可依。"""
    rate = _risk_free_rate(risk_free)
    if rate is None:
        return {
            "mode": "config",
            "note": "未取到该市场的长期国债收益率，折现率沿用配置里的假设值。",
        }
    pol = {**DEFAULT_DISCOUNT_POLICY, **(policy or {})}
    return {
        "mode": "treasury",
        "risk_free_rate": round(rate, 6),
        "benchmark": risk_free.get("label"),
        "as_of": risk_free.get("as_of"),
        "source": risk_free.get("source"),
        "equity_risk_premium": float(pol["equity_risk_premium"]),
        "scenario_spread": dict(pol.get("scenario_spread") or {}),
        "note": "折现率 = 该市场长期国债收益率 + 股权风险溢价，情景再加减价差。",
    }


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value, digits: int = 4):
    return None if value is None else round(value, digits)


def owner_earnings_from(capital_metrics: dict):
    """从资本回报指标里取自由现金流作为折现基数；取不到返回 None。

    自由现金流 = 经营现金流 − 资本开支，近似股东盈余（所有者盈利）。
    """
    block = ((capital_metrics or {}).get("metrics") or {}).get("free_cash_flow") or {}
    if not block.get("available"):
        return None
    return _num(block.get("fcf"))


def project(base: float, growth_rate: float, years: int) -> list[float]:
    """按增长率逐年外推（第 1 年即 base*(1+g)）。"""
    return [base * (1 + growth_rate) ** year for year in range(1, years + 1)]


def discount_to_present(flows: list[float], discount_rate: float) -> list[float]:
    """折现到现值（第 1 年折 1 期）。"""
    return [flow / (1 + discount_rate) ** (i + 1) for i, flow in enumerate(flows)]


def intrinsic_value(base: float, assumptions: dict) -> float:
    """单个情景的内在价值：显式期现值 + Gordon 永续终值现值。"""
    rate = float(assumptions["discount_rate"])
    growth = float(assumptions["growth_rate"])
    terminal_growth = float(assumptions["terminal_growth"])
    years = int(assumptions["years"])
    if rate <= terminal_growth:
        raise ValueError("折现率必须大于永续增长率，否则估值无意义")

    flows = project(base, growth, years)
    pv_explicit = sum(discount_to_present(flows, rate))
    terminal_value = flows[-1] * (1 + terminal_growth) / (rate - terminal_growth)
    pv_terminal = terminal_value / (1 + rate) ** years
    return pv_explicit + pv_terminal


def compute_sensitivity(base: float, years: int, sensitivity: dict) -> dict:
    """敏感性网格：折现率 × 永续增长率 → 内在价值。"""
    rates = [float(r) for r in sensitivity.get("discount_rates", [])]
    growths = [float(g) for g in sensitivity.get("terminal_growths", [])]
    grid: list[list[float | None]] = []
    for rate in rates:
        row: list[float | None] = []
        for growth in growths:
            if rate <= growth:
                row.append(None)  # 该组合无意义，如实留空
                continue
            row.append(
                _round(
                    intrinsic_value(
                        base,
                        {
                            "discount_rate": rate,
                            "growth_rate": DEFAULT_SCENARIOS["base"]["growth_rate"],
                            "terminal_growth": growth,
                            "years": years,
                        },
                    )
                )
            )
        grid.append(row)
    return {"discount_rates": rates, "terminal_growths": growths, "grid": grid,
            "note": "各行对应一个折现率，各列对应一个永续增长率；单位与折现基数相同"}

def compute_valuation(
    capital_metrics: dict,
    price=None,
    shares=None,
    scenarios: dict | None = None,
    years: int | None = None,
    required_margin: float | None = None,
    sensitivity: dict | None = None,
    risk_free: dict | None = None,
    discount_policy: dict | None = None,
) -> dict:
    """三情景内在价值 + 敏感性 + 安全边际区间。

    ``risk_free`` 传该市场的长期国债收益率块（``get_macro_indicators`` 的输出）时，
    折现率改为**以它加股权风险溢价为锚**，敏感性网格也跟着围绕新基准展开；
    不传或取不到就退回 ``scenarios`` / 默认写死费率，并在 ``discount_basis`` 里注明。

    基数（自由现金流）不可得时返回 ``available=False`` 并说明原因，绝不臆造数字。
    """
    grid = {**DEFAULT_SENSITIVITY, **(sensitivity or {})}
    rf = _risk_free_rate(risk_free)
    if rf is not None:
        anchor = rf + float(
            {**DEFAULT_DISCOUNT_POLICY, **(discount_policy or {})}["equity_risk_premium"]
        )
        grid = {**grid, "discount_rates": [round(anchor + d, 4) for d in (-0.02, -0.01, 0.0, 0.01, 0.02)]}

    if rf is not None and scenarios is None:
        # 有国债基准且调用方没显式指定情景 → 按市场锚定折现率
        scen = anchored_scenarios(rf, discount_policy)
    else:
        scen = {**DEFAULT_SCENARIOS, **(scenarios or {})}

    horizon = int(years or DEFAULT_YEARS)
    required = float(DEFAULT_REQUIRED_MARGIN if required_margin is None else required_margin)

    base = owner_earnings_from(capital_metrics)
    if base is None or base <= 0:
        return {
            "available": False,
            "reason": "缺少正的自由现金流基数，无法做折现估值（需先补齐财务数据）",
        }

    # ---- 三情景内在价值 ----
    results: dict[str, dict] = {}
    for key, assumptions in scen.items():
        merged = {**assumptions, "years": horizon}
        if float(merged["discount_rate"]) <= float(merged["terminal_growth"]):
            results[key] = {
                "label": SCENARIO_LABELS.get(key, key),
                "available": False,
                "reason": "折现率必须大于永续增长率，该情景参数无意义",
                "assumptions": merged,
            }
            continue
        value = intrinsic_value(base, merged)
        results[key] = {
            "label": SCENARIO_LABELS.get(key, key),
            "available": True,
            "assumptions": {
                "discount_rate": float(merged["discount_rate"]),
                "growth_rate": float(merged["growth_rate"]),
                "terminal_growth": float(merged["terminal_growth"]),
                "years": horizon,
            },
            "intrinsic_value": _round(value),
        }

    available_values = [
        r["intrinsic_value"] for r in results.values() if r.get("available")
    ]
    low, high = (min(available_values), max(available_values)) if available_values else (None, None)

    out: dict = {
        "available": bool(available_values),
        "basis": {"free_cash_flow": _round(base)},
        "years": horizon,
        "scenarios": results,
        "intrinsic_range": {"low": low, "high": high},
        "required_margin_of_safety": required,
        "discount_basis": discount_basis(risk_free, discount_policy),
        "note": "以上估值由确定性代码按给定假设计算，任何智能体只能引用，不得改动或重算。",
    }

    # ---- 敏感性 ----
    out["sensitivity"] = compute_sensitivity(base, horizon, grid) if available_values else None

    # ---- 市场对比与安全边际区间 ----
    price = _num(price)
    shares = _num(shares)
    if price is None or not shares:
        out["market"] = None
        out["margin_of_safety"] = None
        out["data_gaps"] = ["缺少当前价格或总股本，无法计算安全边际（本维度的核心证据）"]
        return out

    market_cap = price * shares
    out["market"] = {
        "price": _round(price, 6),
        "shares": _round(shares, 4),
        "market_cap": _round(market_cap),
    }

    # 安全边际 = (内在价值 − 市值) / 内在价值；分别对基准情景与最保守情景计算
    mos: dict[str, float | None] = {}
    per_share: dict[str, float | None] = {}
    for key, block in results.items():
        if not block.get("available") or not block["intrinsic_value"]:
            mos[key] = None
            per_share[key] = None
            continue
        value = block["intrinsic_value"]
        mos[key] = _round((value - market_cap) / value)
        per_share[key] = _round(value / shares, 6)

    out["margin_of_safety"] = mos
    out["intrinsic_value_per_share"] = per_share
    # 保守判定：以最悲观情景为准，避免用乐观情景给自己壮胆
    conservative = mos.get("pessimistic") if mos.get("pessimistic") is not None else mos.get("base")
    out["conservative_margin"] = conservative
    out["meets_required_margin"] = (
        None if conservative is None else conservative >= required
    )
    return out
