"""agent 上下文：标的描述 / 语言指令。

``instrument_context`` 是「企业：名称（代码，市场）」这句话的**唯一定义处**。
分析师和汇总师都调它，避免两处各写一份、改一处漏一处——历史上就漏过：
另一份读的是不存在的 ``company_ticker``，ticker 永远是空的。

公司名不是装饰，是给模型的实体锚点：模型据此判断这是哪家公司、该套哪套
会计与监管常识（A 股 vs 美股），并避免把同名公司混进来。所以它跟 ticker
一起进 prompt，而不是只当展示字段。
"""
from ..dataflows.market import MARKET_LABELS
from ..runtime_config import get_config


def _subject(name: str, ticker: str) -> str:
    """名称与代码都在时并列；只有一个时用那个；都空则显式标注。"""
    if name and ticker:
        return f"{name}（{ticker}）"
    return name or ticker or "(未指定标的)"


def instrument_context(state: dict) -> str:
    """给模型看的标的信息行，例如 ``企业：贵州茅台（600519，中国 A 股）``。"""
    ticker = str(state.get("ticker") or "").strip()
    name = str(state.get("company_name") or "").strip()
    # 调用方没填名称时 company_name 会回落到 ticker，别显示成 600519（600519）
    if name == ticker:
        name = ""
    label = MARKET_LABELS.get(str(state.get("market") or "").strip(), "")
    return f"企业：{_subject(name, ticker)}" + (f"，{label}" if label else "")


# 旧名字保留成别名：外部若已引用不至于断
get_instrument_context = instrument_context


def get_language_instruction(language: str | None = None) -> str:
    """显式传入语言优先；未传则读当前运行配置。"""
    from .prompts import language_instruction
    lang = language or get_config().get("output_language", "Chinese")
    return language_instruction(lang)
