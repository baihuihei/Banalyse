"""智能体层：Supervisor 多智能体结构，共 6 个智能体。

    supervisor.py   主管 —— 按 DIMENSION_ORDER 逐个派活（代码判定，不耗 LLM）
    analysts.py     四位维度分析师的公共工厂（按 dimensions.py 声明生成）
    reviewer.py     汇总 —— 把四份维度报告合并成最终报告（只做合并）

    dimensions.py   四维度唯一注册表（唯一真相来源）
    base.py         LLM 调用管道（材料进、自由文本出，保证非空）
    prompts.py      全局约束（框架声明 / 证据纪律 / 不做买卖判断）
    data_block.py   state → 文本块
    guardrails.py   边界机械兜底

四个维度：商业模式 / 管理层 / 财务状况 / 安全边际。
"""

