"""主管调度智能体（Supervisor）。

职责
----
按 ``DIMENSION_ORDER`` 依次把四个维度派给对应分析师，全部完成后转交汇总。
派活（goto）与记账（dispatch_counts）由代码判定，因此：

  · 同样的输入永远走同样的路径，可复现、可测试；
  · 不额外消耗一次 LLM 调用；
  · 某个维度报告为空时自动重派（上限 ``max_attempts``），避免静默丢维度。

四个维度是固定分工，不需要 LLM 现场决策"该谁做"——那只会引入不确定性与成本。
"""
from langgraph.types import Command

from .dimensions import DIMENSION_ORDER

# 汇总节点名（builder.py 用它注册节点）
REVIEWER_NODE = "reviewer"


def create_supervisor(max_attempts: int = 2, dimensions: tuple[str, ...] = DIMENSION_ORDER):
    """返回主管节点。``max_attempts`` 控制单个维度最多派几次。

    ``dimensions`` 必须是**图上真实注册过的**维度子集：主管只派活给注册过的节点，
    否则 LangGraph 会报 "wrote to unknown channel branch:to:xxx" 并静默丢掉这次派活
    —— 表现就是某个维度永远没有报告，而且不报错。
    """

    def node(state):
        reports = state.get("reports") or {}
        counts = dict(state.get("dispatch_counts") or {})

        for key in dimensions:
            # 已有非空报告 → 该维度已完成
            if (reports.get(key) or "").strip():
                continue
            # 重派次数已用尽 → 放弃该维度，交给汇总层如实标注
            if counts.get(key, 0) >= max_attempts:
                continue

            counts[key] = counts.get(key, 0) + 1
            return Command(
                goto=key,
                update={
                    "dispatch_counts": counts,
                    "trace": [f"supervisor→{key} (#{counts[key]})"],
                },
            )

        return Command(
            goto=REVIEWER_NODE,
            update={"dispatch_counts": counts, "trace": ["supervisor→reviewer"]},
        )

    return node
