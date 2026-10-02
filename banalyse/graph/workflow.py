"""对外唯一门面：构建客户端 → 组装 Supervisor 图 → 前向传播。

外部（CLI / 网页端 / 测试）只需要这一个类，不接触图的内部结构。
"""
from datetime import date

from ..dataflows.market import infer_market
from ..llm_clients.factory import build_llm_kwargs, create_llm_client
from ..reporting import write_report
from ..runtime_config import get_config, run_config
from .builder import build_graph


class BanalyseGraph:
    """Banalyse 企业四维度分析图（主管调度 + 4 位分析师 + 汇总）。

    用法（离线 mock）:
        g = BanalyseGraph()
        state = g.analyze("600519", report_date="2026-09-01")
        print(state["final_report"]["conclusion"])

    四个维度：商业模式 / 管理层 / 财务状况 / 安全边际。
    明确边界：只做分析，不判断买还是卖。

    市场由代码形态推断（``600519`` → A 股走 AKShare，``AAPL`` → 美股走 SEC），
    调用方不需要知道这件事。
    """

    def __init__(self, config: dict | None = None, debug: bool = False):
        self.debug = debug
        self.config = {**get_config(), **(config or {})}

    def _clients(self):
        """快速模型跑四个维度分析师，深度模型做汇总。"""
        kw = build_llm_kwargs(self.config)
        provider = self.config["llm_provider"]
        quick = create_llm_client(
            provider, self.config["quick_think_llm"], self.config.get("backend_url"), **kw
        ).get_llm()
        deep = create_llm_client(
            provider, self.config["deep_think_llm"], self.config.get("backend_url"), **kw
        ).get_llm()
        return quick, deep

    def initial_state(self, ticker: str, company: str, report_date: str, market: str) -> dict:
        """图的初始状态（公开以便测试与自定义调用）。

        ``company`` 与 ``ticker`` 一起进 state，两者都会进模型 prompt
        （见 ``agents/context.instrument_context``）：名称是实体锚点，
        代码是数据源主键，缺哪个都会让模型猜。
        """
        return {
            "messages": [("human", f"分析 {ticker}：商业模式 / 管理层 / 财务状况 / 安全边际。")],
            "ticker": ticker,
            "company_name": company or ticker,
            "report_date": str(report_date),
            "market": market,
            # 前置证据
            "evidence": {},
            "capital": {},
            "valuation": {},
            # 四维度报告 + 派活计数
            "reports": {},
            "dispatch_counts": {},
            # 汇总交付
            "review": {},
            "final_report": {},
            "trace": [],
        }

    def analyze(self, ticker: str, company: str = "", report_date=None):
        """跑完整条流水线，返回最终状态（含 state['final_report'] 与 result_path）。

        ``company`` 是**给模型看的实体名**，不是单纯的展示字段：它跟着 ticker
        一起进 state，并出现在每个分析师与汇总师的 prompt 里，帮模型锁定主体、
        选对会计与监管常识。留空时回落到 ticker。

        市场不由调用方决定，而是按 ``ticker`` 形态推断，
        避免"选了 A 股链却传了美股代码"这类错配。
        """
        cfg = self.config
        market = infer_market(ticker)
        report_date = report_date or date.today().strftime("%Y-%m-%d")

        with run_config(cfg):
            quick, deep = self._clients()
            graph = build_graph(quick, deep, cfg)
            init = self.initial_state(ticker, company, report_date, market)
            final = graph.invoke(init, config={"recursion_limit": cfg.get("max_recur_limit", 100)})

        final["result_path"] = write_report(
            cfg.get("results_dir", "results"), ticker, report_date, final
        )
        return final
