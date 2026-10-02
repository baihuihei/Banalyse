"""末端确定性节点：把四份维度报告 + 汇总结论组装成最终交付物。

纯字符串拼装，不再调用 LLM —— 保证「文档里出现的数字/结论都来自上游已确认的内容」。

产出 ``state['final_report']``，包含：
  · markdown   —— 完整分析报告（人读 / 网页展示）
  · 各维度报告、汇总结论与正文、确定性计算结果（结构化，供网页端与落盘使用）
"""
from ...agents.dimensions import DIMENSION_ORDER, dimension_title
from ...dataflows.market import market_label


def build_markdown(state: dict) -> str:
    """把状态拼成完整分析报告（纯确定性字符串拼装）。"""
    ticker = state.get("ticker", "")
    name = state.get("company_name") or ticker
    review = state.get("review") or {}
    reports = state.get("reports") or {}

    parts = [
        f"# {name}（{ticker}）企业分析报告",
        f"分析基准日：{state.get('report_date', '')}　|　市场：{market_label(state.get('market'))}",
        "## 维度分析",
    ]
    for key in DIMENSION_ORDER:
        title = dimension_title(key)
        parts.append(f"### {title}\n{(reports.get(key) or '（该维度报告缺失）').strip()}")

    parts.append("## 汇总")
    parts.append(f"### 综合结论\n{review.get('conclusion') or '（无）'}")
    if review.get("document"):
        parts.append(f"### 报告正文\n{review['document']}")
    if review.get("disclaimer"):
        parts.append(review["disclaimer"])

    parts.append("## 附：确定性计算结果")
    parts.append(f"### 财务指标\n```\n{state.get('capital')}\n```")
    parts.append(f"### 估值\n```\n{state.get('valuation')}\n```")
    return "\n\n".join(parts)


def make():
    """返回 node(state)：组装 state['final_report']。"""

    def node(state):
        review = state.get("review") or {}
        final_report = {
            "company": {
                "ticker": state.get("ticker"),
                "name": state.get("company_name"),
                "report_date": state.get("report_date"),
                "market": state.get("market"),
            },
            # 四维度报告
            "reports": {key: (state.get("reports") or {}).get(key, "") for key in DIMENSION_ORDER},
            # 汇总
            "conclusion": review.get("conclusion", ""),
            "analysis_document": review.get("document", ""),
            "disclaimer": review.get("disclaimer", ""),
            "guardrail": review.get("guardrail", {}),
            # 确定性命数据
            "capital": state.get("capital", {}),
            "valuation": state.get("valuation", {}),
            # 完整文档
            "markdown": build_markdown(state),
        }
        return {"final_report": final_report, "trace": ["assemble"]}

    return node
