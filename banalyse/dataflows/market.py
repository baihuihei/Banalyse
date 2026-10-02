"""按股票代码形态推断市场 —— 用户不再需要手工选「国内 / 海外」。

规则（刻意保持简单可预测）
--------------------------
  纯数字  → ``china``   （A 股 / 北交所代码，6 位）
  含字母  → ``global``  （美股等字母代码的市场）

为什么先剥后缀再判形态
----------------------
A 股在 Yahoo 等口径下会写成 ``600519.SS`` / ``000001.SZ``，这是纯数字代码的
等价写法。若不先剥掉 ``.SS`` / ``.SZ`` / ``.SH`` / ``.BJ``，这两个字母会把
``600519.SS`` 误判成美股。剥后缀是**等价写法归一化**，不是另立一套规则。

市场决定供应商链（见 ``router.vendor_chain``）
---------------------------------------------
  china  → AKShare          （A 股全套材料；SEC 没有 A 股申报主体）
  global → SEC EDGAR        （申报原文与 XBRL 财报的权威来源）

推断结果同时会写进 ``state["market"]`` 与报告正文，便于回溯"这次用的哪条链"。
"""
import re

# A 股代码的等价后缀写法（大小写不敏感）
_A_SHARE_SUFFIXES = (".SS", ".SZ", ".SH", ".BJ")

_DIGITS_ONLY = re.compile(r"^[0-9]+$")

# 市场键 → 中文展示名（报告正文用；缺失则回落到键本身）
MARKET_LABELS = {
    "china": "中国 A 股",
    "global": "海外（美股）",
}

# 市场 → 数据源名（给用户看的解释；与 registry 里的供应商名对应）
MARKET_VENDORS = {
    "china": "AKShare",
    "global": "SEC EDGAR",
}

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 交易所前缀写法：sh600519 / sz000001 —— 很多人习惯这么写，但含字母会被判成美股
_EXCHANGE_PREFIX = re.compile(r"^(sh|sz|bj)[0-9]{6}$", re.IGNORECASE)


def ticker_problem(ticker: str) -> str | None:
    """校验股票代码；有问题返回给用户看的一句话，没问题返回 None。

    为什么要拦：市场是按代码形态推断的，而**含字母或汉字一律判为美股走 SEC**。
    把公司名或 ``sh600519`` 填进代码框，SEC 里自然什么都查不到，
    结果是四个维度全部报告"材料未取到" —— 看起来像数据源坏了，
    实际是代码填法把市场带到了另一条链上。宁可在入口把话说清楚。
    """
    text = str(ticker or "").strip()
    if not text:
        return "请填写股票代码。"
    if _CJK.search(text):
        return (
            f"「{text}」看着像公司名。股票代码请填纯数字（A 股，如 600519）"
            "或字母代码（美股，如 AAPL）；公司名请填在下面的「公司名称」栏。"
        )
    if _EXCHANGE_PREFIX.match(text):
        return (
            f"「{text}」带了交易所前缀。请去掉 sh/sz/bj，直接填 6 位数字（如 {text[2:]}）——"
            "带字母会被判为美股并走 SEC，取不到 A 股数据。"
        )
    core = text.upper()
    for suffix in _A_SHARE_SUFFIXES:
        if core.endswith(suffix):
            core = core[: -len(suffix)]
            break
    if core.isdigit() and len(core) == 5:
        return (
            f"「{text}」是 5 位数字，更像港股代码。"
            "目前只支持 A 股（6 位数字，如 600519）与美股（字母代码，如 AAPL）。"
        )
    return None


def infer_market(ticker: str) -> str:
    """纯数字（含 ``.SS`` 等价后缀）→ ``china``；其余 → ``global``。"""
    core = str(ticker or "").strip().upper()
    for suffix in _A_SHARE_SUFFIXES:
        if core.endswith(suffix):
            core = core[: -len(suffix)]
            break
    return "china" if _DIGITS_ONLY.match(core) else "global"


def market_label(market: str) -> str:
    """市场键 → 中文展示名。"""
    return MARKET_LABELS.get(str(market or ""), str(market or ""))
