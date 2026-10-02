"""时点完整性：确保任何数据都不晚于运行日期 trade_date。"""
from datetime import datetime


def _to_date(s: str):
    # yyyy-mm-dd 片段解析；带时间则只取日期
    return datetime.strptime(str(s)[:10], "%Y-%m-%d")


def as_of(date_str: str, trade_date: str | None = None) -> str:
    """把 date_str 钳制到 trade_date 之前（含 equal），防止未来数据泄漏。"""
    if not trade_date:
        return date_str
    try:
        if _to_date(date_str) > _to_date(trade_date):
            return str(trade_date)[:10]
    except ValueError:
        return str(trade_date)[:10]
    return date_str


def as_of_window(start: str, end: str, trade_date: str | None = None) -> tuple[str, str]:
    """钳制一个 [start, end] 窗口到 trade_date 内。"""
    end = as_of(end, trade_date)
    if start and end:
        try:
            if _to_date(start) > _to_date(end):
                start = end
        except ValueError:
            start = end
    return start, end
