"""CLI（typer）。屏蔽图内部结构，外部只依赖 BanalyseGraph。"""
import os

import typer
from rich.console import Console

from banalyse.agents.dimensions import DIMENSION_ORDER, dimension_title
from banalyse.default_config import DEFAULT_CONFIG
from banalyse.graph.workflow import BanalyseGraph

app = typer.Typer(help="Banalyse 企业四维度分析（商业模式 / 管理层 / 财务状况 / 安全边际）")
console = Console()


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="股票代码，如 600519（A 股）或 AAPL（美股）"),
    company: str = typer.Option("", "--company", "-c", help="公司名称；留空用代码"),
    report_date: str = typer.Option("", "--date", help="分析基准日 yyyy-mm-dd，默认今天"),
):
    """生成企业四维度分析报告（非买卖建议）。

    市场由代码形态推断：纯数字=A 股（AKShare），含字母=美股（SEC EDGAR）。
    """
    g = BanalyseGraph(config=DEFAULT_CONFIG.copy())
    state = g.analyze(ticker, company or ticker, report_date or None)
    final = state.get("final_report") or {}

    reports = final.get("reports") or {}
    for key in DIMENSION_ORDER:
        console.print(f"[bold cyan]{dimension_title(key)}[/bold cyan]")
        console.print((reports.get(key) or "（缺失）").strip())
        console.print("")

    console.print(f"[bold]综合结论[/bold]\n{final.get('conclusion', '')}\n")
    console.print(f"[dim]执行轨迹: {' → '.join(state.get('trace') or [])}[/dim]")
    console.print(f"[dim]已落盘  : {state.get('result_path')}[/dim]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址；局域网访问用 0.0.0.0"),
    port: int = typer.Option(8000, "--port", "-p", help="监听端口"),
    reload: bool = typer.Option(False, "--reload", help="代码热重载（开发用）"),
):
    """启动网页端（浏览器里配模型 / 生成报告 / 与豆包对话）。"""
    import uvicorn

    from banalyse.web.app import create_app

    console.print(f"[bold]网页端:[/bold] http://{host}:{port}")
    if reload:
        os.environ["BA_WEB_HOST"] = host
        os.environ["BA_WEB_PORT"] = str(port)
        uvicorn.run("banalyse.web.app:create_app", factory=True, host=host, port=port, reload=True)
    else:
        uvicorn.run(create_app(), host=host, port=port)


def run():
    app()


if __name__ == "__main__":
    run()
