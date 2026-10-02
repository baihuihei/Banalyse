"""A 股公司概况：主营介绍（同花顺）+ 主体信息（东财）+ 股本（东财 F10）。

来源分工与各自的可靠性
----------------------
  · ``stock_zyjs_ths``（同花顺-主营介绍）→ 主营业务 / 产品类型 / 产品名称 / 经营范围
    商业模式维度主要吃这几项，实测稳定可用，是这份 profile 的主力。
  · ``stock_individual_info_em``（东财快照）→ 股票简称 / 行业 / 上市时间
    走 ``push2`` 主机，**实测可能被拒连**，所以拿到就填、拿不到就标缺失。
  · ``stock_zh_a_gbjg_em``（东财 F10）→ 总股本 / 流通股本
    走 ``emweb`` 主机，实测可用，是股本的可靠兜底。

三个来源各自独立失败，只要有一项有值就返回；全空才算这个槽位无数据。
"缺失"会显式写进 ``missing``，而不是用别的字段冒充。
"""
from ....errors import NoDataError
from . import (
    VENDOR,
    code_of,
    is_frame,
    item_number,
    item_text,
    latest_share_capital,
    require_akshare,
    soft,
)

# 参与"这份 profile 有没有内容"判定的字段
_MEANINGFUL = ("main_business", "business_scope", "name", "industry", "shares")


def _cell(row, column: str):
    if row is None or column not in row.index:
        return None
    raw = row.get(column)
    text = str(raw).strip() if raw is not None else ""
    return text or None


def call(symbol: str) -> dict:
    ak = require_akshare()
    code = code_of(symbol)

    business = soft(ak.stock_zyjs_ths, symbol=code)
    info = soft(ak.stock_individual_info_em, symbol=code)
    business_row = business.iloc[0] if is_frame(business) else None

    shares = item_number(info, "总股本") if is_frame(info) else None
    floating = item_number(info, "流通股") if is_frame(info) else None
    shares_as_of = None
    if shares is None:
        shares, floating, shares_as_of = latest_share_capital(ak, symbol)

    out = {
        "symbol": symbol,
        "code": code,
        "source": VENDOR,
        "market": "china",
        "currency": "CNY",
        # ---- 主营（同花顺）----
        "main_business": _cell(business_row, "主营业务"),
        "products": _cell(business_row, "产品名称") or _cell(business_row, "产品类型"),
        "business_scope": _cell(business_row, "经营范围"),
        # ---- 主体信息（东财快照；可能拿不到）----
        "name": item_text(info, "股票简称") if is_frame(info) else None,
        "industry": item_text(info, "行业") if is_frame(info) else None,
        "listing_date": item_text(info, "上市时间") if is_frame(info) else None,
        # ---- 股本（东财 F10 兜底）----
        "shares": shares,
        "float_shares": floating,
        "shares_as_of": shares_as_of,
        "market_cap": item_number(info, "总市值") if is_frame(info) else None,
        "note": (
            "主营来自同花顺，主体信息来自东财快照（push2 主机，可能被拒连），"
            "股本可回落到东财 F10 股本结构。上市时间口径为 YYYYMMDD。"
        ),
    }

    missing = [key for key in _MEANINGFUL if not out.get(key)]
    out["missing"] = missing
    if len(missing) == len(_MEANINGFUL):
        raise NoDataError(symbol, "主营介绍与个股信息均未返回内容（上游可能被限流）")
    return out
