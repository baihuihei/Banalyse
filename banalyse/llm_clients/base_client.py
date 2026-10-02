"""LLM 客户端抽象基类。"""
from abc import ABC, abstractmethod
from typing import Any


class BaseLLMClient(ABC):
    """抽象基类：产出一个可被 LangChain node 调用的 ``llm`` 对象。"""

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs

    def get_provider_name(self) -> str:
        return "generic"

    @abstractmethod
    def get_llm(self) -> Any:
        """返回配置好的 LangChain LLM 实例。"""

    @abstractmethod
    def validate_model(self) -> bool:
        """校验模型是否在已知目录中。"""
