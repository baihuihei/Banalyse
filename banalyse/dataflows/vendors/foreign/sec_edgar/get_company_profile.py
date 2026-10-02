"""公司概况 —— 直接来自 EDGAR 的申报主体元数据。

为什么够用
----------
``submissions`` 里带着申报主体最关键的身份信息：SIC 行业代码与描述、注册地、
财年结束日、上市交易所与代码、EIN/LEI、官网、办公地址。这些**公司自报**的字段
比第三方加工的"公司简介"更可靠，而且不需要额外下载任何文件。

注意业务描述（10-K Item 1 Business）不在这里取：它属于 ``filings_10k`` 槽位，
重复下载一份 10-K 只为摘一段文字是浪费。
"""
from ..._shared import ensure
from . import VENDOR, submissions_for

# 取哪些字段：都是"申报主体身份"，不含判断性内容
FIELDS = (
    "name", "entityType", "sic", "sicDescription", "stateOfIncorporation",
    "stateOfIncorporationDescription", "fiscalYearEnd", "tickers", "exchanges",
    "ein", "lei", "category", "website", "investorWebsite", "description",
)


def call(symbol: str) -> dict:
    cik, payload = submissions_for(symbol)

    profile = {key: payload[key] for key in FIELDS if payload.get(key)}
    profile["cik"] = cik

    # 曾用名很能说明问题（重组 / 更名 / 借壳），有就带上
    former = [
        {"name": row.get("name"), "from": row.get("from"), "to": row.get("to")}
        for row in payload.get("formerNames") or []
    ]
    if former:
        profile["formerNames"] = former

    # 办公地址只保留城市与州，完整街道地址对分析没用
    business = ((payload.get("addresses") or {}).get("business") or {})
    address = {k: business.get(k) for k in ("city", "stateOrCountry", "stateOrCountryDescription")
               if business.get(k)}
    if address:
        profile["businessAddress"] = address

    return ensure(profile, symbol, VENDOR, "EDGAR 未返回申报主体信息")
