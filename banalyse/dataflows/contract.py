"""数据方法契约：每类数据的统一入口名 + 类别 + 是否可降级。

可插拔的根基：供应商只需实现这些同名函数即可被路由到。
四个分析维度需要什么，就在这里声明什么（见 core/agents/dimensions.py 的 evidence 字段）。
"""
from typing import NamedTuple


class DataMethod(NamedTuple):
    name: str
    category: str           # 分类，用于配置供应商链
    optional: bool = False  # True=可降级类别，失败不中止运行


DATA_METHODS: dict[str, DataMethod] = {
    m.name: m
    for m in [
        # 商业模式维度
        DataMethod("get_company_profile", "profile"),
        DataMethod("get_filing", "filings", optional=True),      # 10-K / DEF 14A 原文
        # 资本回报维度
        DataMethod("get_financials", "fundamental"),
        # 安全边际维度
        DataMethod("get_quote", "core_price", optional=True),    # 现价与总股本
        DataMethod("get_price_history", "core_price", optional=True),
        DataMethod("get_peer_metrics", "valuation", optional=True),  # 可比公司估值
        DataMethod("get_macro_indicators", "macro", optional=True),  # 无风险利率等
        # 共同参考
        DataMethod("get_news", "news", optional=True),
    ]
}

# 可降级类别：拿不到就跳过并在报告里标注，不影响其他维度
OPTIONAL_CATEGORIES = {"profile", "filings", "macro", "news", "valuation", "core_price"}


def is_optional(method: str) -> bool:
    m = DATA_METHODS.get(method)
    return bool(m and m.optional) or bool(m and m.category in OPTIONAL_CATEGORIES)
