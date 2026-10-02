"""通用 agent 助手：把材料喂给 LLM、拿回非空文本。

关于结构化输出：本项目**刻意不用**
-----------------------------------
不再调用 ``llm.with_structured_output``（即 provider 的 ``response_format`` /
function calling）。原因有两条，都是踩过的坑：

1. **支持度参差**：DeepSeek 直接 400 ``This response_format type is unavailable
   now``，而 langchain-openai 只在 bind 阶段不报错、到 invoke 才炸，于是每个节点
   都要白打一轮注定失败的请求（4 个维度 + 汇总 = 多花 6 次往返）。
2. **假成功**：schema "合法"但字段全空的返回会被当成成功，静默产出一份空报告
   —— 比报错更糟，因为没人知道它失败了。

所以改为：**材料原样进、分析自由出**。需要机器处理的字段由
``reviewer.split_sections`` 按 Markdown 标题从自由文本里切
（现在只切“综合结论/报告正文”两节）。切不出来也只是退化成
"整篇都是正文"，不会失败。
"""
import logging

logger = logging.getLogger(__name__)

# 输出为空时的兜底标记：宁可显式写出来，也不给下游留空
EMPTY_REPLY = "（模型返回空响应，本段无内容）"


def as_prompt_value(prompt):
    """把 ChatPromptTemplate 转成可直接喂给 LLM 的 PromptValue。

    本仓库的 prompt 都已完全格式化（无剩余变量），故用 ``{}`` 求值；
    若已是 PromptValue / 消息列表则原样返回。
    """
    return prompt.invoke({}) if hasattr(prompt, "invoke") else prompt


def content_to_text(content) -> str:
    """把消息 content 规范成非空字符串：容忍 None 与分块列表。

    推理型模型把 token 预算耗在 reasoning 上时 ``content`` 会是 ``None``，
    某些 provider 还会返回 ``[{"type": "text", ...}]`` 这种分块结构。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                parts.append(str(block.get("text") or ""))
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()


def invoke_text(llm, prompt, agent_name: str, retries: int = 1) -> str:
    """调 LLM，返回**非空**自由文本。

    绝不返回空串或 None：空报告会在下游表现成"该维度报告缺失"，
    而且与"根本没跑"无法区分。拿不到内容就显式写出来。
    """
    messages = as_prompt_value(prompt)

    for attempt in range(retries + 1):
        try:
            reply = llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001 —— 各家 provider 异常类型不可枚举
            logger.warning("%s: 调用失败 (%s: %s)", agent_name, type(exc).__name__, exc)
            if attempt < retries:
                continue
            return f"（{agent_name} 调用失败：{type(exc).__name__}: {exc}）"

        text = content_to_text(getattr(reply, "content", reply))
        if text:
            return text
        logger.warning("%s: 模型返回空内容（第 %d 次尝试）", agent_name, attempt + 1)

    return EMPTY_REPLY
