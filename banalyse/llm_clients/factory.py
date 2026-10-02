"""LLM 客户端工厂：惰性导入 + 按 provider 分发 + 构建 kwargs。"""
from typing import Any

from .base_client import BaseLLMClient


def create_llm_client(provider: str, model: str, base_url: str | None = None, **kwargs) -> BaseLLMClient:
    """按 provider 构建客户端。依赖惰性导入，避免测试收集时拉重 SDK。"""
    from .providers import PROVIDER_REGISTRY

    p = provider.lower()
    spec = PROVIDER_REGISTRY.get(p)
    if spec is None:
        raise ValueError(f"Unsupported LLM provider: {provider}. Known: {sorted(PROVIDER_REGISTRY)}")

    if spec["kind"] == "mock":
        from .mock_client import MockClient
        return MockClient(model, base_url, **kwargs)

    if spec["kind"] == "openai_compatible":
        from .openai_client import OpenAIClient
        url = base_url or spec.get("base_url")
        # 兼容调用方显式传入 api_key_env（如测试），避免关键字重复
        env = kwargs.pop("api_key_env", None) or spec.get("env")
        return OpenAIClient(model, url, provider=p, api_key_env=env, **kwargs)

    if p == "openai":
        from .openai_client import OpenAIClient
        env = kwargs.pop("api_key_env", None) or spec.get("env")
        return OpenAIClient(model, base_url, provider=p, api_key_env=env, **kwargs)

    # native_anthropic / native_google 在后续里程碑实现
    raise NotImplementedError(
        f"Provider '{provider}' native client is not implemented yet; "
        "use an OpenAI-compatible provider (deepseek/qwen/zhipu/ollama/openai)."
    )


def build_llm_kwargs(config: dict) -> dict[str, Any]:
    """从配置提取跨 provider 的通用 kwargs。

    含 ``api_key``（若配置提供）：让网页端/程序化调用传入的 key 直达客户端，
    无需写进环境变量；未提供时客户端回退到 api_key_env。
    """
    kwargs: dict[str, Any] = {}
    temperature = config.get("temperature")
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    max_tokens = config.get("max_tokens")
    if max_tokens:
        kwargs["max_tokens"] = int(max_tokens)
    api_key = config.get("api_key")
    if api_key:
        kwargs["api_key"] = api_key
    return kwargs
