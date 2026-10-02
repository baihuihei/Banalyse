"""A 股现价与股本：``get_quote`` 槽位在 A 股市场**唯一**的来源。

SEC 结构上没有行情价格，所以 A 股的"股价安全边际"能不能算，
完全取决于这里拿不拿得到 ``price`` 与 ``shares``。

价格：三家依次尝试（不复权）
----------------------------
实测东财 ``push2`` 行情端点会持续拒连，所以价格不能只问东财：

  1. 东财 ``stock_individual_info_em``（字段最全：最新价 + 总股本 + 总市值）
  2. 腾讯 ``stock_zh_a_hist_tx``（最后一根日线的收盘价）
  3. 新浪 ``stock_zh_a_daily``（最后一根日线的收盘价）

价格一律取**不复权**：前复权序列的末值虽然通常等于现价，但除权日前后会
整体平移，用它当"今天该值多少钱"是不严谨的。

股本：东财 F10 是可靠的
-----------------------
``stock_zh_a_gbjg_em``（``emweb`` F10 主机）实测**可用** —— 被挡的是 ``push2``
行情主机，不是东财整体。所以股本的兜底是它，而不是"算不出来"。

市值口径
--------
``market_cap`` 优先用东财自报值；拿不到时用 ``price × shares`` 自己算，
并在 ``market_cap_source`` 里标明是推算的 —— 不静默混淆两种来源。
"""
from datetime import date, timedelta

from ....errors import NoDataError
from ..._shared import to_float
from . import (
    VENDOR,
    code_of,
    exchange_prefixed,
    first_frame,
    is_frame,
    item_number,
    item_text,
    latest_share_capital,
    require_akshare,
    soft,
)

# 用日线末根取现价时的回溯天数（覆盖长假）
RECENT_DAYS = 15


def _last_close(ak, prefixed: str):
    """从日线末根取不复权收盘价；返回 ``(价格, 来源名)``。"""
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=RECENT_DAYS)).strftime("%Y%m%d")

    attempts = [
        ("腾讯", ak.stock_zh_a_hist_tx, {
            "symbol": prefixed, "start_date": start, "end_date": end, "adjust": "",
        }),
        ("新浪", ak.stock_zh_a_daily, {"symbol": prefixed, "adjust": ""}),
    ]
    frame, label, _ = first_frame(attempts)
    if frame is None:
        return None, None

    for close_column in ("close", "收盘"):
        if close_column not in frame.columns:
            continue
        for index in range(len(frame) - 1, -1, -1):
            value = to_float(frame[close_column].iloc[index])
            if value is not None:
                return value, label
    return None, None


def call(symbol: str) -> dict:
    ak = require_akshare()
    code = code_of(symbol)
    prefixed = exchange_prefixed(symbol)

    warnings: list[str] = []

    # ---- 价格：东财快照优先（字段最全），失败则用日线末根 ----
    info = soft(ak.stock_individual_info_em, symbol=code)
    price = to_float(item_number(info, "最新", "现价")) if is_frame(info) else None
    price_source = "东财快照" if price is not None else None
    if price is None:
        price, price_source = _last_close(ak, prefixed)
        if price_source:
            warnings.append(f"东财行情端点不可用，现价改用{price_source}日线末根收盘价")

    # ---- 股本：东财快照 → 东财 F10 ----
    shares = to_float(item_number(info, "总股本")) if is_frame(info) else None
    floating = to_float(item_number(info, "流通股")) if is_frame(info) else None
    shares_source = "东财快照" if shares is not None else None
    shares_as_of = None
    if shares is None:
        shares, floating, shares_as_of = latest_share_capital(ak, symbol)
        if shares is not None:
            shares_source = "东财F10股本结构"
            warnings.append("东财快照不可用，总股本改用 F10 股本结构最新一条")

    if price is None and shares is None:
        raise NoDataError(symbol, "现价与总股本都取不到（东财/腾讯/新浪全部失败）")

    # ---- 市值：优先东财自报，否则自己算 ----
    market_cap = to_float(item_number(info, "总市值")) if is_frame(info) else None
    if market_cap is not None:
        market_cap_source = "东财自报"
    elif price is not None and shares:
        market_cap = round(price * shares, 2)
        market_cap_source = "price × shares（本模块推算）"
    else:
        market_cap_source = None

    out = {
        "symbol": symbol,
        "code": code,
        "source": VENDOR,
        "currency": "CNY",
        "price": price,
        "price_source": price_source,
        "shares": shares,
        "shares_source": shares_source,
        "shares_as_of": shares_as_of,
        "market_cap": market_cap,
        "market_cap_source": market_cap_source,
        "float_shares": floating,
        "name": item_text(info, "股票简称") if is_frame(info) else None,
        "note": (
            "现价为**不复权**市价（东财快照或日线末根收盘，见 price_source）。"
            "股本来自发行人口径，可用于计算市值；market_cap_source 标明市值是"
            "东财自报还是本模块推算，两者不混用。"
        ),
    }

    if price is None:
        warnings.append("未取到现价：安全边际的市价侧无法计算，只能在报告里标注缺口")
    if not shares:
        warnings.append("未取到总股本：无法计算市值，安全边际同样无法计算")
    if warnings:
        out["warnings"] = warnings
    return out
