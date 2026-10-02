"""EDGAR XBRL 财报 —— 资本回报与估值两条链的财务数据入口。

为什么用 XBRL 而不是第三方接口
------------------------------
yahoo 之类的非官方接口会限流、且给的是二手加工数据；SEC 的 XBRL
``companyfacts`` 是公司**自己申报**的原始数字（口径可追溯），
免 key、限流宽松（10 req/s）。

口径处理
--------
· **时点科目**（资产、权益、现金）没有 ``start``，只有 ``end``；
  **期间科目**（收入、净利润、现金流）有 ``start`` + ``end``，需按
  "跨度约一年"筛掉季报。
· 同一报告期常有多条（原始申报 + 后续修订 + 多年对比），
  按 ``filed`` 取最新的那条 —— 这是 XBRL 取数最容易取错的地方。
· 各字段覆盖的年份区间不同，必须经 :func:`align_periods` **按年对齐**后再输出，
  否则 ``domain/capital.py`` 的按位置相除会拿错年份。
"""
from datetime import date

from ..._shared import align_periods, ensure, to_float
from . import VENDOR, facts_for

# 契约字段 → (类别, us-gaap 标签候选)
# 类别：instant=时点（资产负债表），duration=期间（利润表 / 现金流量表）
TAGS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("revenue", "duration", (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
    )),
    ("gross_profit", "duration", ("GrossProfit",)),
    ("operating_income", "duration", ("OperatingIncomeLoss",)),
    ("net_income", "duration", ("NetIncomeLoss", "ProfitLoss")),
    ("shareholders_equity", "instant", (
        "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    )),
    ("total_assets", "instant", ("Assets",)),
    ("cash", "instant", (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    )),
    ("total_debt", "instant", ("LongTermDebtNoncurrent", "LongTermDebt", "DebtLongtermAndShorttermCombinedAmount")),
    ("operating_cash_flow", "duration", ("NetCashProvidedByUsedInOperatingActivities",)),
    ("capital_expenditure", "duration", (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    )),
    ("dividends_paid", "duration", ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock")),
)

# 年度期间的合法跨度（天）。取宽一点容错 52/53 周财年。
_YEAR_DAYS = (330, 400)


def _annual_map(entries: list[dict], kind: str) -> dict[int, float]:
    """把某个标签下的原始条目整理成 ``{年: 值}``（同年多条取最新申报）。"""
    best: dict[int, tuple[str, float]] = {}          # 年 → (filed, 数值)
    for entry in entries:
        if not str(entry.get("form", "")).startswith("10-K"):
            continue                                  # 只要年报，不要 10-Q 季报
        if entry.get("fp") and entry["fp"] != "FY":
            continue
        value = to_float(entry.get("val"))
        end = str(entry.get("end") or "")[:10]
        if value is None or not end:
            continue

        if kind == "duration":
            start = str(entry.get("start") or "")[:10]
            if not start:
                continue
            try:
                span = (date.fromisoformat(end) - date.fromisoformat(start)).days
            except ValueError:
                continue
            if not (_YEAR_DAYS[0] <= span <= _YEAR_DAYS[1]):
                continue
        elif entry.get("start"):
            continue                                  # 时点科目不该有 start

        try:
            year = date.fromisoformat(end).year
        except ValueError:
            continue

        filed = str(entry.get("filed") or "")
        if year not in best or filed >= best[year][0]:
            best[year] = (filed, value)

    return {year: value for year, (_, value) in best.items()}


def call(symbol: str) -> dict:
    cik, facts_all = facts_for(symbol)
    # 走缓存的 company_facts：get_quote 也要读同一份十几 MB 的文件
    facts = (facts_all.get("facts") or {}).get("us-gaap") or {}

    # 先按字段收集 {年: 值}，最后统一对齐到同一组年份（各标签覆盖区间不同）
    per_field: dict[str, dict[int, float]] = {}
    for field, kind, tags in TAGS:
        for tag in tags:
            block = facts.get(tag) or {}
            units = block.get("units") or {}
            entries = units.get("USD") or units.get("shares") or []
            values = _annual_map(entries, kind)
            if values:
                per_field[field] = values
                break

    series, years = align_periods(per_field)
    out: dict = {"symbol": symbol, "source": VENDOR, "cik": cik}
    if years:
        out["fiscal_years"] = list(years)
        out.update(series)

    have_equity = out.get("net_income") and out.get("shareholders_equity")
    return ensure(out if have_equity else None, symbol, VENDOR,
                  "XBRL companyfacts 未返回可用年度数据（缺净利润或净资产）")
