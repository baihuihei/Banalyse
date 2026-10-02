"""Mock LLM：无 key 离线运行，供 M0 骨架与测试使用。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .base_client import BaseLLMClient


class MockChatModel(BaseChatModel):
    """固定输出一段示例文本；支持 bind_tools(返回自身) 以兼容上游节点。"""

    model_name: str = "mock"
    temperature: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "mock"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        content = (
            "[M0 mock]\n"
            "公司基本面稳健，营收保持增长，估值处于行业合理区间。"
            "（接入真实 LLM：设置 BA_LLM_PROVIDER=deepseek 或 openai，并配置对应 API key）"
        )
        message = AIMessage(content=content)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        # M0 的 mock 不真正调用工具，直接返回自身，避免上游 bind_tools 崩溃。
        return self

    def with_structured_output(self, schema, **kwargs):
        # 故意不支持结构化输出，逼上游走自由文本回退路径（用于测试回退逻辑）。
        raise NotImplementedError("MockChatModel does not support with_structured_output")


class MockClient(BaseLLMClient):
    def __init__(self, model="mock-chat", base_url=None, **kwargs):
        super().__init__(model, base_url, **kwargs)
        self.provider = "mock"

    def get_provider_name(self) -> str:
        return "mock"

    def get_llm(self) -> MockChatModel:
        return MockChatModel(model_name=self.model)

    def validate_model(self) -> bool:
        return True
