#!/usr/bin/env python
"""Banalyse 入口：四维度企业分析（默认离线 mock）。

用法：
    python main.py                          # mock，离线
    BA_LLM_PROVIDER=deepseek python main.py # 接真实模型（需配 DEEPSEEK_API_KEY）
"""
from rich.console import Console
from rich.panel import Panel

from banalyse.agents.dimensions import DIMENSION_ORDER, dimension_title
from banalyse.default_config import DEFAULT_CONFIG
from banalyse.graph.workflow import BanalyseGraph

console = Console()


def main(ticker: str = "600519.SS", company: str = "贵州茅台", report_date: str = "2026-09-01"):
    g = BanalyseGraph(config=DEFAULT_CONFIG.copy(), debug=True)
    state = g.analyze(ticker, company, report_date)
    final = state.get("final_report") or {}

    console.print(Panel.fit(
        f"[bold]市场:[/bold] {state.get('market')} | [bold]标的:[/bold] {ticker} | "
        f"[bold]公司:[/bold] {state.get('company_name')} | "
        f"[bold]日期:[/bold] {report_date} | [bold]provider:[/bold] {DEFAULT_CONFIG['llm_provider']}",
        title="Banalyse · 企业四维度分析",
    ))

    # 四个维度的子报告
    reports = final.get("reports") or {}
    for key in DIMENSION_ORDER:
        text = (reports.get(key) or "（缺失）").strip()
        console.print(f"[bold cyan]{dimension_title(key)}[/bold cyan]")
        console.print(text)
        console.print("")

    # 汇总
    console.print("[bold]汇总[/bold]")
    console.print(final.get("conclusion") or "（空）")
    console.print("")

    console.print(f"[dim]执行轨迹:[/dim] {' → '.join(state.get('trace') or [])}")
    console.print(f"[dim]已落盘  :[/dim] {state.get('result_path')}")
    console.print("[dim]本文档为分析，不构成买卖建议。[/dim]")


if __name__ == "__main__":
    main()
