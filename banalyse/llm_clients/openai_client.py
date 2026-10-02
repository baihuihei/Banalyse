"""OpenAI 兼容客户端：国内外通用主力（国内厂商走 langchain-openai）。"""
import os

from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient


class OpenAIClient(BaseLLMClient):
    """使用 langchain_openai.ChatOpenAI；国内厂商只需改 base_url。

    api_key 解析优先级：显式传入（如网页端配置） > 环境变量 api_key_env。
    这样网页端填的 key 无需写进进程环境变量，也不影响 CLI 的 env 用法。
    """

    def __init__(
        self,
        model,
        base_url=None,
        provider="openai",
        api_key_env=None,
        api_key=None,
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider
        self.api_key_env = api_key_env or "OPENAI_API_KEY"
        self.api_key = api_key

    def get_provider_name(self) -> str:
        return self.provider

    def resolve_api_key(self) -> str | None:
        """显式 key 优先，其次环境变量；都没有则返回 None 交给 SDK 报错。"""
        return self.api_key or os.getenv(self.api_key_env)

    def get_llm(self):
        return ChatOpenAI(
            model=self.model,
            base_url=self.base_url,
            api_key=self.resolve_api_key(),
            **self.kwargs,
        )

    def validate_model(self) -> bool:
        return True
