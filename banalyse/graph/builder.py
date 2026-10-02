"""LangGraph 组装：Supervisor 多智能体拓扑。

    START
      → collect_evidence      前置：拉取全部原始材料（确定性）
      → compute_capital       前置：算资本回报指标（确定性）
      → compute_valuation     前置：算三情景估值（确定性）
      → supervisor  ←──────────────┐        主管按 DIMENSION_ORDER 逐个派活
           ├─ business_model ─────┤
           ├─ management ─────────┤        四个维度分析师（Command 动态派发）
           ├─ capital_return ─────┤
           └─ margin_of_safety ───┘
      → reviewer              汇总：把四份报告合并成完整研究文档
      → assemble              确定性打包（markdown / 落盘结构）
      → END

节点间的派发由 supervisor 返回 ``Command(goto=...)`` 完成，
因此 supervisor 不能有静态出边（LangGraph 的约束），分析师则统一静态回到 supervisor。
"""
from langgraph.graph import END, START, StateGraph

from ..agents.analysts import create_analyst
from ..agents.dimensions import DIMENSION_ORDER
from ..agents.reviewer import create_reviewer
from ..agents.supervisor import REVIEWER_NODE, create_supervisor
from ..runtime_config import get_config
from .nodes import assemble, collect_evidence, compute_capital, compute_valuation
from .state import CompanyAnalysisState

SUPERVISOR_NODE = "supervisor"
ASSEMBLE_NODE = "assemble"


def build_graph(quick_llm, deep_llm, config: dict | None = None):
    """组装并编译图。

    ``quick_llm`` 用于四个维度分析师（调用次数多，重速度）；
    ``deep_llm`` 用于汇总（一次调用，重质量）。
    """
    cfg = config or get_config()
    dimensions = list(cfg.get("dimensions") or DIMENSION_ORDER)
    language = cfg.get("output_language", "Chinese")

    unknown = [key for key in dimensions if key not in DIMENSION_ORDER]
    if unknown:
        raise ValueError(f"未知分析维度：{unknown}；已知：{list(DIMENSION_ORDER)}")

    graph = StateGraph(CompanyAnalysisState)

    # ---- 前置确定性节点 ----
    graph.add_node("collect_evidence", collect_evidence.make())
    graph.add_node("compute_capital", compute_capital.make())
    graph.add_node("compute_valuation", compute_valuation.make())

    # ---- 主管 + 四个维度分析师 ----
    # 主管只遍历"本次真正注册的维度"，否则会派给不存在的节点：
    # LangGraph 只会警告 "wrote to unknown channel" 并丢掉派活，不报错。
    graph.add_node(
        SUPERVISOR_NODE,
        create_supervisor(int(cfg.get("max_dispatch_attempts", 2)), dimensions=tuple(dimensions)),
    )
    for key in dimensions:
        graph.add_node(key, create_analyst(key, quick_llm, language))
        graph.add_edge(key, SUPERVISOR_NODE)      # 每次交活后回到主管

    # ---- 汇总 + 打包 ----
    graph.add_node(REVIEWER_NODE, create_reviewer(deep_llm, language))
    graph.add_node(ASSEMBLE_NODE, assemble.make())

    # ---- 主干边 ----
    graph.add_edge(START, "collect_evidence")
    graph.add_edge("collect_evidence", "compute_capital")
    graph.add_edge("compute_capital", "compute_valuation")
    graph.add_edge("compute_valuation", SUPERVISOR_NODE)
    graph.add_edge(REVIEWER_NODE, ASSEMBLE_NODE)
    graph.add_edge(ASSEMBLE_NODE, END)
    # supervisor 的出边由 Command(goto=...) 动态给出，不能静态声明

    return graph.compile()

