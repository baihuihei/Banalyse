"""全局约束与公共 prompt 片段。

三块内容，全部是"给所有智能体的共同纪律"：
  · ANALYSIS_FRAMEWORK  —— 分析框架声明（四维度分工）
  · EVIDENCE_DISCIPLINE —— 证据纪律：只用给定材料、缺数据要明说、不得编造
  · NO_ADVICE_RULE      —— 边界：只做分析，不判断买还是卖
"""
from textwrap import dedent


def language_instruction(language: str = "Chinese") -> str:
    """输出语言指令（内部推理可仍用英文）。"""
    if not language or str(language).lower() == "english":
        return ""
    return (
        f"\n\nWrite the output in {language}. "
        "Internal reasoning may stay in English, but the final text must be in that language. "
        "Use plain UTF-8 text; no markdown unless required."
    )


# 分析框架：四个维度各由一名分析师负责，最后交由汇总节点合并
ANALYSIS_FRAMEWORK = dedent(
    """\
    本次分析采用卖方研究框架，把企业拆成四个相互独立的维度，每个维度由一名分析师负责：
      1) 商业模式   —— 赚钱方式、逐年经营历史、相对同行的优势
      2) 管理层作为 —— 战略选择、资本配置、股权激励、高管履历与诚信、收购/回购/分红决策
      3) 财务状况   —— 利润率、投资收益比（ROIC）、近五年 ROE、股东盈余
      4) 安全边际 —— 相对估值、DCF 三情景、敏感性、下行风险、安全边际空间
    你只负责自己被指派的那一个维度，不要越界评价其他维度——那是其他分析师的职责。
    """
)

# 证据纪律：对抗幻觉的核心约束
EVIDENCE_DISCIPLINE = (
    "【证据纪律】只依据提示词中提供的材料作答；每条结论都要能对应到具体材料内容。"
    "材料缺失时必须在 data_gaps 中明确指出缺什么，禁止臆测、禁止编造数字或业务事实。"
    "系统给出的确定性计算结果（财务指标 / 估值）只能引用与解读，不得改动或自行重算。"
    "严格区分【事实陈述】（材料里写明的）与【主观推断】（你的判断），推断需注明是推断。"
)

# 边界：只做分析，不判断买还是卖
# 刻意**不列举**具体禁用词：模型会"复述禁令"来表示遵从，而那些词正好会被
# guardrails.find_advice_terms 命中，把合规声明误判成违规（并触发删行）。
NO_ADVICE_RULE = (
    "【不可逾越的边界】你只做「分析」，绝不判断买还是卖。"
    "不给出任何操作方向、价值判断口径或价格结论，也不给出隐含的择时结论。"
    "另外：不要在输出里复述本条禁令，也不要列举被禁止的词汇。"
    "你的产出是分析，不是建议。"
)

