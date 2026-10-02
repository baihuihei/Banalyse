"""A 股财报：新浪三大报表 → 契约字段的年度序列。

为什么不用「关键指标」表（第一版就是错的）
------------------------------------------
``stock_financial_abstract``（关键指标）看起来最省事，实测把 80 个指标名列出来
才发现它**只有比率和每股口径**（毛利率 / ROE / 每股净资产 …），
根本没有契约需要的**绝对金额科目**：资产总计、货币资金、负债合计、
资本开支、股利支付全部不在里面，用它只能凑出 revenue / net_income 两项。
所以改用 ``stock_financial_report_sina`` 的三大报表 —— 科目齐全，且免 key。

口径处理（三处必须小心）
------------------------
1. **只取年报行**（``报告日`` 以 ``1231`` 结尾），季报/中报一律丢弃。
   ``domain/capital.py`` 的比率计算假设各序列是**等长年度**序列，
   混入季报会让同比与均值全错。
2. **优先取合并报表**（``类型`` 含「合并」）。同一报告日可能既有合并口径
   又有母公司口径，混用会让"净利润"和"股东权益"口径不一致。
3. **精确匹配科目名**。候选名逐个精确比对，匹配不到就留空；绝不退化成
   包含匹配 —— 把「扣非净利润」当「净利润」、把「营业总收入」当「营业收入」
   都是不报错但数字错的典型。候选名里把**归母口径放前面**，
   让 net_income 与 shareholders_equity 同属"归属母公司"口径，ROE 才有意义。

各字段覆盖年份可能不同，输出前必须经 :func:`align_periods` 按年份交集对齐，
否则 ``domain/capital.py`` 的按位置相除会拿错年份。
"""
import re

from ....errors import NoDataError
from ..._shared import align_periods, to_float
from . import VENDOR, code_of, exchange_prefixed, is_frame, require_akshare, soft

# 契约字段 → (来源报表, 候选科目名)。候选顺序即优先级。
_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # ---- 利润表 ----
    ("revenue", "利润表", ("营业总收入", "营业收入")),
    ("operating_income", "利润表", ("营业利润",)),
    ("net_income", "利润表", ("归属于母公司所有者的净利润", "净利润")),
    # ---- 资产负债表 ----
    ("shareholders_equity", "资产负债表",
     ("归属于母公司股东权益合计", "所有者权益(或股东权益)合计")),
    ("total_assets", "资产负债表", ("资产总计",)),
    ("cash", "资产负债表", ("货币资金",)),
    ("total_debt", "资产负债表", ("负债合计",)),
    # ---- 现金流量表 ----
    ("operating_cash_flow", "现金流量表", ("经营活动产生的现金流量净额",)),
    ("capital_expenditure", "现金流量表", (
        "购建固定资产、无形资产和其他长期资产所支付的现金",
        "购建固定资产、无形资产和其他长期资产支付的现金",
    )),
    ("dividends_paid", "现金流量表", (
        "分配股利、利润或偿付利息所支付的现金",
        "分配股利、利润或偿付利息支付的现金",
    )),
)

# 营业成本：只用来自己减出 gross_profit，不是契约字段
_COST_NAMES = ("营业成本",)

SHEETS = ("资产负债表", "利润表", "现金流量表")

_ANNUAL_DATE = re.compile(r"^[0-9]{4}1231$")


def _annual_rows(frame):
    """筛出「合并口径」的行；返回 ``(frame, 报告日字符串列)``。"""
    if "类型" in frame.columns:
        kinds = frame["类型"].astype(str)
        consolidated = frame[kinds.str.contains("合并", na=False)]
        if not consolidated.empty:
            frame = consolidated
    dates = frame["报告日"].astype(str).str.strip()
    return frame, dates


def _series(frame, dates, names: tuple[str, ...]) -> dict[int, float]:
    """按候选科目名取 ``{年: 值}``；多个候选名只认第一个命中列。"""
    target = None
    for name in names:
        if name in frame.columns:
            target = name
            break
    if target is None:
        return {}

    values = frame[target]
    out: dict[int, float] = {}
    for index in range(len(frame)):
        raw_date = dates.iloc[index]
        if not _ANNUAL_DATE.match(raw_date):
            continue
        value = to_float(values.iloc[index])
        if value is None:
            continue
        # 行按报告期从新到旧排列；同一年多条时保留最先遇到的（最新修订）
        out.setdefault(int(raw_date[:4]), value)
    return out


def call(symbol: str) -> dict:
    ak = require_akshare()
    code = code_of(symbol)
    stock = exchange_prefixed(symbol)          # 新浪口径 sh600519

    sheets: dict[str, object] = {}
    failed: list[str] = []
    for sheet in SHEETS:
        frame = soft(ak.stock_financial_report_sina, stock=stock, symbol=sheet)
        if is_frame(frame) and "报告日" in frame.columns:
            sheets[sheet] = frame
        else:
            failed.append(sheet)

    if not sheets:
        raise NoDataError(symbol, f"新浪三大报表全部取不到（失败：{failed}）")

    filtered = {sheet: _annual_rows(frame) for sheet, frame in sheets.items()}

    per_field: dict[str, dict[int, float]] = {}
    for field, sheet, names in _FIELDS:
        if sheet not in filtered:
            continue
        frame, dates = filtered[sheet]
        series = _series(frame, dates, names)
        if series:
            per_field[field] = series

    if not per_field:
        raise NoDataError(symbol, "三大报表里没有匹配到任何契约科目（上游可能改了科目名）")

    # 毛利率需要 gross_profit，而报表里只有「营业成本」，所以自己减一次
    if "利润表" in filtered:
        frame, dates = filtered["利润表"]
        revenue = per_field.get("revenue")
        cost = _series(frame, dates, _COST_NAMES)
        if revenue and cost:
            gross = {year: revenue[year] - cost[year] for year in revenue if year in cost}
            if gross:
                per_field["gross_profit"] = gross

    aligned, years = align_periods(per_field)
    if not aligned or not years:
        raise NoDataError(symbol, "各科目没有共同的年报年份，无法对齐（不能按位置硬算）")

    all_fields = [field for field, _, _ in _FIELDS] + ["gross_profit"]
    return {
        "symbol": symbol,
        "code": code,
        "source": VENDOR,
        "currency": "CNY",
        "unit": "元",
        "years": years,
        "statement_sheets": sorted(sheets),
        **aligned,
        "note": (
            "来自新浪三大报表的**合并年报**口径；已按年份交集对齐，"
            "可安全按位置做比率运算。净利润与股东权益均为**归属母公司**口径，"
            "两者同源，ROE 才有意义。缺失字段表示该期未取到，不代表为 0。"
        ),
        "missing": [field for field in all_fields if field not in aligned],
        "failed_sheets": failed,
    }
