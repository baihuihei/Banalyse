"""拉取最新 10-K / DEF 14A 正文。

为什么必须截断
--------------
10-K 原文动辄 5-20 MB HTML，整篇塞进 prompt 会直接超上下文上限并烧掉大量
token。这里两步压缩：先剥 HTML 成纯文本，再**按章节优先**截断 ——
把 Item 1 / 1A / 7 / 7A 这些真正有信息量的段落往前放，凑够上限即止。

截断是显式声明的（返回里带 ``truncated`` 与提示），所以 LLM 知道
"材料不完整"而不是以为自己看到了全文。
"""
import re

from ..._shared import ensure
from . import VENDOR, raw_filing

# 单份文件送进 prompt 的字符上限（约 15k token 量级）
MAX_CHARS = 60_000

# 章节优先级提示词：命中这些标记的段落优先保留
SECTION_HINTS = (
    # 10-K
    "item 1.", "item 1a.", "item 1b.", "item 7.", "item 7a.", "item 8.",
    "business", "risk factors", "management's discussion",
    # DEF 14A（管理层薪酬与资本配置）
    "executive compensation", "compensation discussion", "principal stockholders",
    # 8-K（重大事件）
    "item 2.01", "item 2.02", "item 2.06", "item 5.02",
)

_SCRIPTS = re.compile(r"(?is)<(script|style|ix:header)\b.*?</\1>")
_TAGS = re.compile(r"(?s)<[^>]+>")
_SPACES = re.compile(r"[ \t\u00a0]{2,}")
_BLANKS = re.compile(r"\n{3,}")
_ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&#8217;": "'", "&#8216;": "'", "&#8220;": '"', "&#8221;": '"',
    "&#8212;": "—", "&#160;": " ",
}


def html_to_text(html: str) -> str:
    """剥掉 HTML 标签与实体；表格会退化成逐格换行，可接受。"""
    text = _SCRIPTS.sub(" ", html)
    text = _TAGS.sub("\n", text)
    for source, target in _ENTITIES.items():
        text = text.replace(source, target)
    text = _SPACES.sub(" ", text)
    return _BLANKS.sub("\n\n", text).strip()


def trim_by_section(text: str, limit: int = MAX_CHARS) -> tuple[str, bool]:
    """按章节优先级把正文压到 ``limit`` 以内；返回 (文本, 是否被截断)。"""
    if len(text) <= limit:
        return text, False

    blocks = [block.strip() for block in text.split("\n\n") if len(block.strip()) > 80]
    if not blocks:                                   # 没有可切分的段落，硬截
        return text[:limit], True

    priority = [b for b in blocks if any(h in b[:400].lower() for h in SECTION_HINTS)]
    others = [b for b in blocks if b not in priority]

    kept: list[str] = []
    size = 0
    for block in priority + others:
        if size + len(block) > limit:
            continue                                 # 跳过长段落，继续试短的
        kept.append(block)
        size += len(block)

    if not kept:                                     # 单段就超限，硬截第一段
        return priority[0][:limit] if priority else blocks[0][:limit], True
    return "\n\n".join(kept), True


def call(symbol: str, form_type: str = "10-K") -> dict:
    meta = raw_filing(symbol, form_type)
    text, truncated = trim_by_section(html_to_text(meta["html"]))
    return ensure(
        {
            "symbol": symbol,
            "form": form_type,
            "cik": meta["cik"],
            "accession": meta["accession"],
            "filed": meta["filed"],
            "source_url": meta["source_url"],
            "chars": len(text),
            "truncated": truncated,
            "text": text,
            "note": "原文过长已按章节优先截断" if truncated else "完整正文",
        },
        symbol, VENDOR, f"{form_type} 正文为空",
    )
