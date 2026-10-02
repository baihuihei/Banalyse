"""供应商公共工具：key 检查、依赖惰性导入、DataFrame 取值。

为什么集中在这里
----------------
九个数据槽位背后是六个供应商，但"怎么取 key、怎么导入重依赖、怎么把
DataFrame 变成契约字段"这三件事对所有供应商完全一样。集中一份，
供应商模块就只剩"这家 API 怎么调"这一件真正不同的事。

两条铁律
--------
1. 重依赖（如 requests）一律在 ``call()`` 内部导入。
   缺包会抛 ImportError，router 会把它当作「该供应商不可用」跳到下一家，
   于是"没装依赖"和"这家拿不到、换下一家"是同一条代码路径。
2. 拿不到数据一律抛 :class:`NoDataError`，绝不允许返回 None / 空 dict ——
   非空返回会被上游当成"数据正常"，比缺数据更危险（会写出没有依据的结论）。
"""
import os
from typing import Any

from ..errors import NoDataError, VendorNotConfiguredError


def require_env(name: str, vendor: str) -> str:
    """取必需的环境变量；缺失时抛「未配置」，router 会跳过该供应商。"""
    value = (os.getenv(name) or "").strip()
    if not value:
        raise VendorNotConfiguredError(f"{vendor} 需要环境变量 {name}")
    return value


def require_dependency(module: str, vendor: str):
    """惰性导入重依赖。缺包抛 ImportError —— 这是 router 认得的"跳过"信号。"""
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise ImportError(f"{vendor} 需要安装 {module}（pip install {module}）: {exc}") from exc


def to_float(value: Any) -> float | None:
    """宽松转 float；不可转或 NaN 一律 None（不抛异常，不产生 nan 传播）。"""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN != NaN


def ensure(payload, symbol: str, vendor: str, detail: str = ""):
    """空结果升级为 NoDataError，避免"静默成功"污染下游报告。"""
    if payload is None or payload == {} or payload == [] or payload == "":
        raise NoDataError(symbol, f"{vendor}: {detail or 'no payload'}")
    return payload


def align_periods(per_field: dict[str, dict[int, float]]) -> tuple[dict[str, list[float]], list[int]]:
    """把 ``{字段: {年: 值}}`` 对齐成同一组年份的**等长**序列。

    为什么必须对齐
    --------------
    ``domain/capital.py`` 是按**位置**对齐的：它认为 ``net_income[i]`` 和
    ``shareholders_equity[i]`` 是同一年。但各字段覆盖的年份区间并不一致
    （实测 AAPL：revenue 9 年、equity 20 年），直接往下传就会出现
    "用 2024 年的净利润除以 2025 年的净资产" —— 不报错，但数字是错的。
    实测这个 bug 会把 ROE 算成 188%、ROIC 算成 86%。

    取所有字段**年份集合的交集**，这样每个字段都能提供每一个年份的值，
    位置对齐才成立。完全不重叠时退化为"以覆盖最广的字段为基准"。
    返回 ``(对齐后的序列, 年份列表)``。
    """
    maps = {field: values for field, values in per_field.items() if values}
    if not maps:
        return {}, []

    common = set.intersection(*(set(values) for values in maps.values()))
    if common:
        years = sorted(common)
        return {field: [values[y] for y in years] for field, values in maps.items()}, years

    # 完全没有共同年份：以覆盖最广的字段为基准，只保留能完整覆盖它的字段
    reference_years = sorted(max(maps.values(), key=len))
    aligned = {
        field: [values[y] for y in reference_years]
        for field, values in maps.items()
        if all(y in values for y in reference_years)
    }
    return aligned, reference_years
