"""红线守卫：本项目**只做利弊分析，不判断买还是卖**。

仅靠 prompt 约束不可靠，故对最终产出做一次机械扫描：
命中交易建议类词汇则重写一次；仍命中则降级为「剥离并加声明」，绝不中断流水线。
"""
import re

# 交易建议 / 评级类词汇（中英）
ADVICE_TERMS = (
    "买入", "卖出", "持有", "增持", "减持", "建议买", "建议卖", "目标价", "评级",
    "推荐买入", "强烈推荐", "清仓", "建仓", "止损", "止盈",
    "buy", "sell", "hold", "overweight", "underweight", "price target", "outperform",
)

# 用词边界匹配英文，避免 "holiday" 之类误伤
_PATTERN = re.compile(
    r"|".join(
        rf"\b{re.escape(t)}\b" if t.isascii() else re.escape(t)
        for t in sorted(ADVICE_TERMS, key=len, reverse=True)
    ),
    re.IGNORECASE,
)

DISCLAIMER = (
    "【声明】本文档仅就企业、管理、财务与市场估值四个方面呈现利与弊，"
    "不构成任何投资建议，也不提供任何交易操作指引。"
)

# 重写时追加给模型的指令
RETRY_INSTRUCTION = (
    "\n\n[硬性约束] 你上一版输出中出现了交易建议类措辞，这是禁止的。"
    "请重写：只陈述有利因素与不利因素、数据缺口与综合评估，"
    "不得出现买入/卖出/持有/增持/减持/评级/目标价等任何投资建议或评级用语。"
)


def find_advice_terms(text: str) -> list[str]:
    """返回文本中命中的交易建议词汇（去重，保持出现顺序）。"""
    if not text:
        return []
    seen: list[str] = []
    for match in _PATTERN.finditer(text):
        token = match.group(0)
        if token.lower() not in [s.lower() for s in seen]:
            seen.append(token)
    return seen


def strip_advice_lines(text: str) -> str:
    """降级方案：删掉包含建议词汇的整行，保留其余内容。"""
    if not text:
        return text
    kept = [line for line in text.splitlines() if not find_advice_terms(line)]
    return "\n".join(kept).strip()


def with_disclaimer(text: str) -> str:
    """在末尾补齐固定声明（若尚未包含）。"""
    if DISCLAIMER in (text or ""):
        return text
    return f"{text}\n\n{DISCLAIMER}"
