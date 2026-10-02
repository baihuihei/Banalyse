"""把 state 中的数据/计算结果渲染成喂给 LLM 的文本块。

刻意只做「给定内容的排版」，不做筛选或推断 —— 数据不足就如实显示，避免 LLM 幻觉。
"""
from typing import Any

_MISSING_HINT = "(缺失)"


def _render_value(value: Any) -> str:
    if value is None:
        return _MISSING_HINT
    if isinstance(value, dict):
        if not value:
            return _MISSING_HINT
        return "\n".join(f"  - {k}: {_render_value(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        if not value:
            return _MISSING_HINT
        return "\n".join(f"  - {_render_value(v)}" for v in value)
    if hasattr(value, "to_markdown"):
        try:
            return str(value.to_markdown())
        except Exception:  # noqa: BLE001 —— 第三方 DataFrame 渲染失败不应中断
            return str(value)
    return str(value)


def build_data_block(source: dict, keys: list[str] | None = None, title: str | None = None) -> str:
    """把 ``source`` 中指定 ``keys`` 渲染成 Markdown 风格文本块。

    keys 为 None 时渲染全部。缺失键会显式标注为「(缺失)」。
    """
    source = source or {}
    selected = keys if keys is not None else list(source)
    lines: list[str] = []
    if title:
        lines.append(f"## {title}")
    for key in selected:
        lines.append(f"## {key}\n{_render_value(source.get(key))}")
    return "\n\n".join(lines) if lines else "(无可用数据)"
