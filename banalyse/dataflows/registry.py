"""供应商能力注册表：声明「需要什么 key / 提供哪些方法 / 面向哪个市场」。

新增供应商 = 在此登记 + 在 vendors/ 下添加模块（同名函数实现契约）。

**两家，按市场分工：**

  · ``sec_edgar``（``global``）—— 免费公开的申报文件库，数据权威（公司自己申报），
    覆盖财报原文与 XBRL 财报；它结构上**没有**行情价格。
  · ``akshare``（``china``）—— A 股免 key 数据源（抓取东财/新浪/同花顺），
    补齐 A 股全套材料，包括 SEC 根本服务不了的行情价格。

市场由股票代码形态推断（见 ``market.infer_market``），不需要用户选，
也不需要新增第三个市场就能插更多的源。
"""
from ..llm_clients.providers import PROVIDER_REGISTRY
from .contract import DATA_METHODS

# requires: 需要的环境变量名；None=免 key
# provides: 实现了契约中的哪些方法（未列出的方法调用时会返回"无数据"哨兵）
# markets:  该供应商只在推断出这个市场时被选中
VENDOR_REGISTRY: dict[str, dict] = {
    "sec_edgar": {
        # 必需：SEC 强制要求请求头带可联系的身份，不给会 403
        "requires": "SEC_EDGAR_USER_AGENT",
        "markets": ["global"],
        "provides": [
            #   10-K / DEF 14A / 8-K 原文（原始 HTML + 章节解析）
            "get_filing",
            #   XBRL companyfacts 年度财报
            "get_financials",
            #   submissions 申报主体元数据（SIC / 注册地 / 财年 / 曾用名）
            "get_company_profile",
            #   封面页总股本（**不含行情价格**）
            "get_quote",
            #   近期 8-K 重大事件（按 item 代码归类）
            "get_news",
            #   美国 10 年期国债收益率（DCF 折现基准；实现委托给共享的 _rates.py）
            "get_macro_indicators",
        ],
    },
    "akshare": {
        # 免 key：公开抓取库，不需要注册
        "requires": None,
        "markets": ["china"],
        "provides": [
            #   主营介绍（同花顺）+ 个股信息（东财：股本/行业/上市日）
            "get_company_profile",
            #   关键指标（新浪）→ 对齐成契约字段的年度序列
            "get_financials",
            #   个股公告标题 + 链接（东财）—— 不是 10-K 原文，能拿多少算多少
            "get_filing",
            #   现价 + 总股本 + 总市值（东财）—— A 股的价格来源
            "get_quote",
            #   日频历史行情（东财，前复权）
            "get_price_history",
            #   个股新闻（东财）
            "get_news",
            #   中国 10 年期国债收益率（DCF 折现基准；实现委托给共享的 _rates.py）
            "get_macro_indicators",
        ],
    },
}

# 说明：只登记**已实现**的供应商。未实现的不要先写进来，
# 否则 vendors_providing() 会把它们当成可选链的一环，运行时才在 ImportError 上落空。


def vendor_market(vendor: str) -> str:
    """供应商所属子包：``china`` 或 ``foreign``（决定从哪个目录加载实现）。

    注意：这里决定的是**代码目录**，不是该供应商服务哪个市场 ——
    服务范围由 ``markets`` + 路由共同决定。两者恰好一致只是巧合。
    保留这套映射是为了新增供应商时不用改路由。
    """
    specs = VENDOR_REGISTRY.get(vendor, {})
    return "china" if specs.get("markets") == ["china"] else "foreign"


def vendors_providing(method: str) -> list[str]:
    """实现了 ``method`` 且已配置 key 的供应商列表。"""
    result = []
    for vendor, spec in VENDOR_REGISTRY.items():
        if method not in spec.get("provides", []):
            continue
        need = spec.get("requires")
        if need and not _env_present(need):
            continue
        result.append(vendor)
    return result


def unconfigured_vendors(method: str) -> list[tuple[str, str]]:
    """实现了 ``method`` 但**缺 key** 的供应商 → ``[(vendor, 需要的环境变量)]``。

    用途：链为空时给出可操作的诊断。否则用户只会看到一句"没有可用供应商"，
    而真正的原因（忘配 ``SEC_EDGAR_USER_AGENT``）得自己去翻代码才能发现。
    """
    blocked = []
    for vendor, spec in VENDOR_REGISTRY.items():
        if method not in spec.get("provides", []):
            continue
        need = spec.get("requires")
        if need and not _env_present(need):
            blocked.append((vendor, need))
    return blocked


def _env_present(name: str) -> bool:
    import os
    val = os.getenv(name)
    return bool(val is not None and val != "")


def providers_ready() -> list[str]:
    """当前可用（key 满足）的 LLM provider 候选。"""
    return [p for p, s in PROVIDER_REGISTRY.items() if not s.get("env") or _env_present(s["env"])]


def validate_methods_exist() -> list[str]:
    """返回声明了但未在契约中定义的方法名（契约漂移检查）。"""
    valid = set(DATA_METHODS)
    declared = {m for s in VENDOR_REGISTRY.values() for m in s.get("provides", [])}
    return sorted(declared - valid)
