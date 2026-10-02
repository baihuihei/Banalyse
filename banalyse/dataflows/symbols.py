"""ticker → 文件系统路径的安全清洗，防止路径遍历。

这里**只做**路径安全。原先还有一组"各供应商符号格式转换"（yahoo 的
``600519.SS`` 后缀、akshare 的纯 6 位代码、新浪的 ``sh600519`` 前缀等），
随多供应商层一起删掉了 —— 单源 SEC EDGAR 直接用 ticker 查 CIK，
不需要任何格式转换。将来再加供应商时，符号映射应该放在那家供应商自己的包里，
而不是这里，避免又长成一个"谁都依赖但谁都不负责"的工具模块。
"""
import re

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_ticker_component(raw: str) -> str:
    """清洗 ticker 用于拼接到文件系统路径；空则返回 'unknown'。"""
    cleaned = _UNSAFE.sub("_", str(raw or "")).strip("._")
    return cleaned if cleaned else "unknown"
