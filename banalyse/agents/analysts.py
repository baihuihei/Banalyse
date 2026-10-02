"""四个维度分析师的公共工厂。

为什么只有一个文件
------------------
四个维度的差异（角色、判读要点、所需材料）全部声明在 ``dimensions.py``，
这里只负责"按声明组装 prompt → 调 LLM → 写回报告"这一件机械的事。
因此不需要四个几乎重复的 agent 文件。

关于数据获取
------------
本项目把"调用外部数据源"放在图的前置确定性节点（collect_evidence / compute_*）完成，
分析师直接读取已就绪的材料。这样避免了让 LLM 在 ReAct 循环里反复试错调工具——
既更省 token、更快、可离线跑，也让「分析师只做推理」这件事更清晰。

关于输出：**纯自由文本**。材料（含系统算好的指标）原样拼进 prompt，
由模型自己写分析，不做任何 schema 约束——理由见 ``base.py`` 的模块注释。
"""
from langchain_core.prompts import ChatPromptTemplate

from .base import invoke_text
from .context import get_language_instruction, instrument_context
from .data_block import build_data_block
from .dimensions import (
    COMPUTED_LABELS,
    DIMENSIONS,
    EVIDENCE_LABELS,
    Dimension,
    get_dimension,
    render_criteria,
)
from .prompts import ANALYSIS_FRAMEWORK, EVIDENCE_DISCIPLINE, NO_ADVICE_RULE


def build_inputs(state: dict, dimension: Dimension) -> str:
    """按维度声明，把该维度需要的材料与计算结果拼成文本块。"""
    chunks: list[str] = []

    evidence = state.get("evidence") or {}
    for slot in dimension.evidence:
        label = EVIDENCE_LABELS.get(slot, slot)
        chunks.append(build_data_block(evidence, [slot], title=label))

    for computed in dimension.computed:
        label = COMPUTED_LABELS.get(computed, computed)
        chunks.append(build_data_block(state.get(computed) or {}, title=label))

    return "\n\n".join(chunks) if chunks else "(无可用材料)"


def build_analyst_prompt(
    state: dict, dimension_key: str, language: str = "Chinese"
) -> ChatPromptTemplate:
    """构造某个维度分析师的完整 prompt（拆出来便于单测）。"""
    dimension = get_dimension(dimension_key)

    system = "\n\n".join(
        [
            dimension.role,
            ANALYSIS_FRAMEWORK,
            f"本次你负责的维度：【{dimension.label}】，判读要点如下（逐条覆盖，但只产出一份报告）：\n"
            f"{render_criteria(dimension)}",
            EVIDENCE_DISCIPLINE,
            NO_ADVICE_RULE,
        ]
    ) + get_language_instruction(language)

    # 标的信息只用共享 helper 拼，保证带上公司名 + 代码 + 市场
    human = (
        f"{instrument_context(state)}\n"
        f"分析基准日：{state.get('report_date', '')}\n\n"
        f"{build_inputs(state, dimension)}\n\n"
        f"请就【{dimension.label}】这一维度给出你的分析。"
    )
    return ChatPromptTemplate.from_messages([("system", system), ("human", human)])


def create_analyst(dimension_key: str, llm, language: str = "Chinese"):
    """返回可被 LangGraph 用作 node 的 ``callable(state)``。"""
    get_dimension(dimension_key)          # 提前校验 key，配置错误要早暴露

    def node(state):
        prompt = build_analyst_prompt(state, dimension_key, language)
        text = invoke_text(llm, prompt, f"analyst:{dimension_key}")
        # reports 用 reduce_merge 合并，同键覆盖；每次只写自己那一个键
        return {
            "reports": {dimension_key: text},
            "trace": [f"analyst:{dimension_key}"],
        }

    return node


def analyst_node_names() -> dict[str, str]:
    """维度 key → 图节点名（当前同名，保留此函数以便将来统一改名）。"""
    return {key: key for key in DIMENSIONS}
