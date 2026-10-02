"""市场基准利率：按标的市场取对应的长期（10 年）国债收益率。

为什么单独一个模块
------------------
国债收益率是**市场级**参考数据，不是某家公司的数据，所以它不属于任何一家
供应商的"公司数据"口径。但估值必须按市场选对无风险基准：

  · A 股 / 港股 → 中国 10 年期国债收益率
  · 美股       → 美国 10 年期国债收益率

两者都在 AKShare 的 ``bond_zh_us_rate``（中美国债收益率）同一张表里，
取一次就够，所以中国链与海外链的 ``get_macro_indicators`` 都委托到这里 ——
不抄两份，将来换源也只改一处。

数据口径
--------
返回值里的 ``rate`` 是**小数**（0.0167 = 1.67%），不是百分数。
"""
import datetime as dt
import logging
from functools import lru_cache

from ..errors import NoDataError
from ..market import infer_market
from ._shared import require_dependency

logger = logging.getLogger(__name__)

VENDOR = "akshare"

# 市场 → (AKShare 列名, 给人看的名称)
RATE_COLUMNS: dict[str, tuple[str, str]] = {
    "china": ("中国国债收益率10年", "中国 10 年期国债收益率"),
    "global": ("美国国债收益率10年", "美国 10 年期国债收益率"),
}

# 一次抓一年多的历史：足够跨过周末与长假期，末尾总能找到最近一个有效值
LOOKBACK_DAYS = 400


@lru_cache(maxsize=4)
def _yield_frame(start_date: str):
    """带缓存地取中美国债收益率表（同一次分析里可能被多次读到）。"""
    akshare = require_dependency("akshare", VENDOR)
    return akshare.bond_zh_us_rate(start_date=start_date)


def _latest(column: str) -> tuple[float, str]:
    """取该列最后一个非空值，返回 (小数形式的收益率, 数据日期)。"""
    start = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    frame = _yield_frame(start)

    if column not in getattr(frame, "columns", []):
        raise NoDataError(f"宏观数据源没有「{column}」列")

    rows = frame[["日期", column]].dropna()
    if rows.empty:
        raise NoDataError(f"「{column}」在最近 {LOOKBACK_DAYS} 天内没有任何有效值")

    row = rows.iloc[-1]
    return float(row[column]) / 100.0, str(row["日期"])


def long_term_treasury(symbol: str) -> dict:
    """按 ``symbol`` 推断出的市场，返回折现用的长期国债收益率。

    取不到数据时抛 :class:`NoDataError`（router 会转成哨兵），
    绝不返回编造的默认利率 —— 折现率是整个估值的地基，不能猜。
    """
    market = infer_market(symbol)
    column, label = RATE_COLUMNS.get(market) or RATE_COLUMNS["global"]
    rate, as_of = _latest(column)

    if not 0 < rate < 0.30:
        # 0 或 30% 以上都不像真实国债收益率，多半是数据源改了口径或单位
        raise NoDataError(f"{label} 取到异常值 {rate}（期望 0~30% 的小数）")

    logger.info("benchmark rate for %s: %s = %.4f (%s)", symbol, label, rate, as_of)
    return {
        "market": market,
        "label": label,
        "rate": round(rate, 6),
        "as_of": as_of,
        "source": "AKShare bond_zh_us_rate（中美国债收益率）",
        "note": "长期国债收益率，按小数表示（0.0167 = 1.67%），用作 DCF 折现率的无风险基准。",
    }
