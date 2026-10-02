"""A 股日频历史行情（前复权）：东财 → 腾讯 → 新浪 依次尝试。

为什么必须三家都试
------------------
实测**东财的行情端点（``push2his``）会持续拒连**（``RemoteDisconnected``，
连试 4 次全败），而腾讯和新浪都正常返回。如果只写东财一家，
A 股的行情槽位就会永久失明 —— 这正是"没有找到数据"的直接原因。

三家返回的列名完全不同（东财中文、腾讯/新浪英文），所以统一在这里
规范化成 ``{date, close, high, low}``，上层只认这一种形状。

为什么默认前复权
----------------
不复权价格遇到送转/分红会出现巨大跳空，用来判断"区间高低点""长期趋势"
会得到假信号。前复权保证序列连续，是算区间收益的正确口径。

但它**不等于当日真实成交价** —— 所以这里只用于趋势与区间判断，
"当前市价"一律以 ``get_quote`` 的**不复权**快照为准，两者在报告里分开标注。

时点完整性
----------
起止日期由调用方按分析基准日倒推（见 ``graph/nodes/collect_evidence.py``），
本模块不自己取"最新" —— 否则用历史基准日回测会泄漏未来数据。
"""
from datetime import date, timedelta

from ....errors import NoDataError
from ..._shared import to_float
from . import (
    VENDOR,
    code_of,
    compact_date,
    exchange_prefixed,
    first_frame,
    require_akshare,
)

# 回溯窗口的兜底值：调用方没给日期时用（正常路径不会走到）
FALLBACK_YEARS = 5
# 返回给 LLM 的最大行数：够看趋势，又不至于把 evidence 撑爆
MAX_ROWS = 60

# 三家上游的列名口径 → (日期, 收盘, 最高, 最低) 的候选列名
_COLUMNS = {
    "东财": (("日期",), ("收盘",), ("最高",), ("最低",)),
    "腾讯": (("date",), ("close",), ("high",), ("low",)),
    "新浪": (("date",), ("close",), ("high",), ("low",)),
}


def _window(start_date: str, end_date: str) -> tuple[str, str]:
    """补齐起止日期到 AKShare 需要的 ``YYYYMMDD`` 口径。"""
    end = compact_date(end_date) or date.today().strftime("%Y%m%d")
    start = compact_date(start_date)
    if not start:
        try:
            base = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
        except (TypeError, ValueError):
            base = date.today()
        start = (base - timedelta(days=365 * FALLBACK_YEARS)).strftime("%Y%m%d")
    return start, end


def _normalize(frame, label: str, start: str, end: str) -> list[dict]:
    """把上游宽表规范成 ``[{date, close, high, low}]``，并按窗口过滤。"""
    date_names, close_names, high_names, low_names = _COLUMNS[label]

    def col(names):
        for name in names:
            if name in frame.columns:
                return frame[name]
        return None

    dates, closes = col(date_names), col(close_names)
    highs, lows = col(high_names), col(low_names)
    if dates is None or closes is None:
        raise NoDataError(label, f"{label} 返回的表缺少日期或收盘列")

    lo, hi = start[:4] + start[4:6] + start[6:8], end
    rows = []
    for index in range(len(frame)):
        raw_date = "".join(ch for ch in str(dates.iloc[index]) if ch.isdigit())[:8]
        if len(raw_date) != 8 or not (lo <= raw_date <= hi):
            continue
        close = to_float(closes.iloc[index])
        if close is None:
            continue
        rows.append({
            "date": f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}",
            "close": close,
            "high": to_float(highs.iloc[index]) if highs is not None else None,
            "low": to_float(lows.iloc[index]) if lows is not None else None,
        })

    rows.sort(key=lambda item: item["date"])
    return rows


def call(symbol: str, start_date: str = "", end_date: str = "") -> dict:
    ak = require_akshare()
    code = code_of(symbol)
    prefixed = exchange_prefixed(symbol)
    start, end = _window(start_date, end_date)

    attempts = [
        # 东财：列名中文；端点可能被拒连，所以只作为第一顺位试一次
        ("东财", ak.stock_zh_a_hist, {
            "symbol": code, "period": "daily",
            "start_date": start, "end_date": end, "adjust": "qfq",
        }),
        # 腾讯：列名英文，支持复权与日期区间
        ("腾讯", ak.stock_zh_a_hist_tx, {
            "symbol": prefixed, "start_date": start, "end_date": end, "adjust": "qfq",
        }),
        # 新浪：列名英文，**不支持日期参数**，取全量后由本模块按窗口过滤
        ("新浪", ak.stock_zh_a_daily, {"symbol": prefixed, "adjust": "qfq"}),
    ]

    frame, label, failed = first_frame(attempts)
    if frame is None:
        raise NoDataError(symbol, f"东财/腾讯/新浪行情全部取不到（失败：{failed}）")

    rows = _normalize(frame, label, start, end)
    if not rows:
        raise NoDataError(symbol, f"{label} 在 {start}~{end} 区间内没有交易日数据")

    first, last = rows[0], rows[-1]
    highs = [row["high"] for row in rows if row["high"] is not None]
    lows = [row["low"] for row in rows if row["low"] is not None]
    change = None
    if first["close"]:
        change = round((last["close"] - first["close"]) / first["close"] * 100, 2)

    return {
        "symbol": symbol,
        "code": code,
        "source": f"{VENDOR}/{label}",
        "currency": "CNY",
        "adjust": "qfq",
        "window": {"start": start, "end": end},
        "summary": {
            "first_date": first["date"],
            "last_date": last["date"],
            "first_close": first["close"],
            "last_close": last["close"],
            "change_pct": change,
            "period_high": max(highs) if highs else None,
            "period_low": min(lows) if lows else None,
        },
        "rows": rows[-MAX_ROWS:],
        "note": (
            f"数据来自 {label}（前复权）。前复权序列连续，适合看趋势与区间位置，"
            "但**不等于当日真实成交价**；当前市价请看 quote 槽位。"
            f"仅返回最近 {MAX_ROWS} 行，统计区间为完整窗口。"
        ),
        "fallback_from": failed,
    }
