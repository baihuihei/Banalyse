"""数据工具封装：LangChain @tool，供 agent 调用；核心做时点处理 + 路由。

参数约定：**所有检索一律只认股票代码**（如 ``600519`` / ``AAPL``），
不接受公司名。两个原因：
  · 市场由代码形态推断，传名字会被当成美股走 SEC，直接取不到 A 股数据；
  · 名字检索会匹配到同名公司，静默取回错主体的数据 —— 比取不到数据危险得多。
公司名只作为给模型看的上下文（见 ``agents/context.instrument_context``），
不参与任何取数。
"""
from typing import Annotated

from langchain_core.tools import tool

from .date_window import as_of_window
from .router import route_to_vendor


@tool
def get_company_profile(
    symbol: Annotated[str, "ticker code only, e.g. AAPL or 600519.SS; never a company name"],
) -> str:
    """Retrieve company profile (name, industry, business summary)."""
    return route_to_vendor("get_company_profile", symbol)


@tool
def get_price_history(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "start date in yyyy-mm-dd"],
    end_date: Annotated[str, "end date in yyyy-mm-dd"],
    trade_date: str = "",  # 由 graph 注入运行日期；M4 改为 InjectedState
) -> str:
    """Retrieve OHLCV price history for a ticker, clamped to the run's trade_date."""
    start_date, end_date = as_of_window(start_date, end_date, trade_date or None)
    return route_to_vendor("get_price_history", symbol, start_date, end_date)


@tool
def get_financials(
    symbol: Annotated[str, "ticker symbol"],
) -> str:
    """Retrieve key financial statements (income / balance / cashflow)."""
    return route_to_vendor("get_financials", symbol)
