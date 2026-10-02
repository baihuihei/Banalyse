"""前置确定性节点：收集四个维度所需的全部原始材料。

为什么要"先集中取数"而不是让每个分析师自己调工具
------------------------------------------------
  · 一次取数、四个维度共用，避免同一份财报被重复拉取；
  · 取数失败只影响一个槽位，不会让分析师在 ReAct 循环里反复试错烧 token；
  · 全部材料先落地到 state["evidence"]，报告里就能统一标注来源。

每个槽位独立容错：失败写入哨兵文本，绝不中断整条流水线。

时点完整性
----------
行情必须按分析基准日**倒推窗口**，而不是取最新——否则用 2020 年的基准日
跑分析却拿到 2026 年的价格，回测就失真了。窗口经 as_of_window 钳制，
保证不晚于 report_date（不泄漏未来数据）。
"""
from datetime import date, timedelta

from ...dataflows.date_window import as_of_window
from ...dataflows.router import route_to_vendor

# 行情回溯年数：够算区间高低点与中期趋势，又不至于拉回几千行
LOOKBACK_YEARS = 5

# (槽位, 契约方法, 附加参数)
# 附加参数可以是元组（字面量）或 "@window"（需按运行时状态算行情窗口）。
SLOTS: tuple[tuple[str, str, object], ...] = (
    ("profile", "get_company_profile", ()),
    ("filings_10k", "get_filing", ("10-K",)),
    ("filings_def14a", "get_filing", ("DEF 14A",)),
    ("financials", "get_financials", ()),
    ("quote", "get_quote", ()),
    ("price_history", "get_price_history", "@window"),
    ("peer_metrics", "get_peer_metrics", ()),
    ("macro_indicators", "get_macro_indicators", ()),
    ("news", "get_news", ()),
)


def _price_window(state) -> tuple[str, str]:
    """按分析基准日倒推 (start, end)，并钳制到基准日之前。"""
    end = str(state.get("report_date") or date.today().isoformat())[:10]
    try:
        start = (date.fromisoformat(end) - timedelta(days=365 * LOOKBACK_YEARS)).isoformat()
    except ValueError:      # 基准日格式异常 → 交给供应商用自己的默认区间
        return "", ""
    return as_of_window(start, end, end)


def _resolve(extra, state) -> tuple:
    """附加参数解析："@window" 表示按基准日算行情窗口。"""
    if extra == "@window":
        return _price_window(state)
    return extra if isinstance(extra, tuple) else ()


def make():
    """返回 node(state)：把全部材料写入 state['evidence']。"""

    def node(state):
        # 检索一律只传股票代码：市场就是按代码形态推断出来的（纯数字=A股/AKShare，
        # 含字母=美股/SEC），公司名一带进去就会把市场带偏；而且按名字搜可能命中
        # 同名公司的数据 —— 静默取回错主体的材料，比取不到更危险。
        # 公司名只进 _meta 作为落档信息，并另外通过 instrument_context 给模型当上下文。
        ticker = state.get("ticker", "")
        evidence: dict = {
            "_meta": {
                "ticker": ticker,
                "company": state.get("company_name", ""),
                "report_date": state.get("report_date", ""),
                "market": state.get("market", ""),
            }
        }

        for slot, method, extra in SLOTS:
            try:
                evidence[slot] = route_to_vendor(method, ticker, *_resolve(extra, state))
            except Exception as exc:  # noqa: BLE001 —— 单槽位失败不应中断整条流水线
                evidence[slot] = (
                    f"DATA_UNAVAILABLE: {method} 抛出 {type(exc).__name__}: {exc}。"
                    "不得据此编造数据。"
                )

        return {"evidence": evidence, "trace": ["collect_evidence"]}

    return node
