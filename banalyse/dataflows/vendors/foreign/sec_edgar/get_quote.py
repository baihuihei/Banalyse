"""EDGAR 能提供的那半份"报价"：总股本（+ 封面页市值锚点）。

**必须说清楚：SEC 不提供行情价格。** 它是申报文件数据库，没有交易所行情。
所以本模块**只填 ``shares``，``price`` 与 ``market_cap`` 一律为 None** ——
宁可让下游明确报"缺现价"，也不用一个陈旧的封面页数字冒充现价。

两个 DEI（封面页事实）：
  · ``EntityCommonStockSharesOutstanding`` —— 申报时的总股本，权威且免费。
    实测与东财的 ``f84`` 完全一致（AAPL 均为 14,594,180,000）。
  · ``EntityPublicFloat`` —— 10-K 封面披露的"非关联方持股市值"，带披露时点。
    它 ÷ 股本可以反推一个**当时**的隐含价，但：① 不含关联方持股；② 时点是
    财年附近而非今天。所以它只作为"市值锚点"放进 ``public_float``，
    绝不写进 ``price``，并且带上 ``as_of`` 让下游自己判断时效。
"""
from ..._shared import ensure, to_float
from . import VENDOR, facts_for, latest_dei


def call(symbol: str) -> dict:
    cik, facts = facts_for(symbol)

    shares, shares_end, shares_form, shares_filed = latest_dei(
        facts, "EntityCommonStockSharesOutstanding", units=("shares",)
    )
    public_float, float_end, _, _ = latest_dei(facts, "EntityPublicFloat", units=("USD",))

    if shares is None and public_float is None:
        return ensure(None, symbol, VENDOR, "EDGAR 未返回股本或公众持股市值")

    out = {
        "symbol": symbol,
        "cik": cik,
        "source": VENDOR,
        # 行情价格：SEC 没有这一项，显式留空，由 price_history/quote 的其它供应商补
        "price": None,
        "market_cap": None,
        "shares": shares,
        "shares_as_of": shares_end,
        "shares_source_form": shares_form,
        "shares_filed": shares_filed,
        "note": (
            "SEC 不含行情，price/market_cap 为空。shares 来自 10-K/10-Q 封面页"
            f"（报告期 {shares_end}，{shares_form}），可直接用于计算市值。"
        ),
    }

    if public_float is not None:
        anchor = {
            "public_float": public_float,
            "as_of": float_end,
            "disclosure": "10-K 封面披露的非关联方持股市值",
        }
        # 只做"锚点"，不叫 price：它既不含关联方持股，也不是当期数据
        implied = (
            round(to_float(public_float) / shares, 4)
            if public_float and shares else None
        )
        if implied:
            anchor["implied_price"] = implied
            anchor["caveat"] = (
                "隐含价 = 公众持股市值 ÷ 总股本，仅对应上述披露时点，"
                "且剔除了关联方持股，**不得当作当前股价使用**"
            )
        out["public_float"] = anchor

    return out
