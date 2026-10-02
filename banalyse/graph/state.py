"""CompanyAnalysisState —— 全图共享状态契约。

字段分四组，与图的四段流程一一对应：

  输入        ticker / company_name / report_date / market
              （market 由 ticker 形态推断而来，不是调用方选项；见 dataflows/market.py）
  前置证据    evidence（原始材料）、capital（资本回报指标）、valuation（估值）
  维度报告    reports（四个维度各一份，supervisor 逐个写入）
  汇总交付    review（综合结论 + 报告正文）、final_report

并行写入约定
------------
  · reports   —— 四个分析师顺序写入（supervisor 逐个派活），仍用 reduce_merge 合并，
                 这样将来改成并行扇出时无需改动状态定义；
  · trace     —— 追加型，用 operator.add，保留完整轨迹。
"""
import operator
from typing import Annotated, Any

from langgraph.graph import MessagesState


def reduce_merge(a: dict | None, b: dict | None) -> dict:
    """dict 合并：不同键互不影响，同键后者覆盖。"""
    return {**(a or {}), **(b or {})}


class CompanyAnalysisState(MessagesState):
    # ---- 输入 ----
    ticker: str
    company_name: str
    report_date: str
    market: str                   # "china" | "global"，由 ticker 推断

    # ---- 前置确定性证据（LLM 只能引用） ----
    evidence: dict[str, Any]      # 原始材料：profile / filings_10k / financials / price_history ...
    capital: dict[str, Any]       # 资本回报指标：ROE / ROIC / FCF ...
    valuation: dict[str, Any]     # 估值：三情景内在价值 / 敏感性 / 安全边际

    # ---- 四维度报告 ----
    reports: Annotated[dict[str, str], reduce_merge]
    dispatch_counts: dict[str, int]   # 主管派活计数，防止维度失败导致死循环

    # ---- 汇总与交付 ----
    review: dict[str, Any]
    final_report: dict[str, Any]


    # ---- 执行轨迹（并行/顺序写入都用追加，避免并发冲突） ----
    trace: Annotated[list[str], operator.add]

