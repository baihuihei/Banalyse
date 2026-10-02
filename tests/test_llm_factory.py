"""LLM 工厂测试。"""
import pytest

from banalyse.llm_clients.factory import build_llm_kwargs, create_llm_client


class TestFactory:
    def test_mock_client(self):
        client = create_llm_client("mock", "mock-chat")
        assert client.get_provider_name() == "mock"
        llm = client.get_llm()
        # mock LLM 可被直接调用（离线）
        resp = llm.invoke("hello")
        assert resp.content

    def test_case_insensitive(self):
        assert create_llm_client("MOCK", "m").get_provider_name() == "mock"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            create_llm_client("not-a-provider", "m")

    def test_openai_compatible_routes(self):
        # deepseek 是 OpenAI 兼容，应路由到 OpenAIClient
        client = create_llm_client("deepseek", "deepseek-chat", base_url="https://x/v1", api_key_env="DEEPSEEK_API_KEY")
        from banalyse.llm_clients.openai_client import OpenAIClient
        assert isinstance(client, OpenAIClient)
        assert client.get_provider_name() == "deepseek"


class TestBuildKwargs:
    def test_temperature_and_tokens(self):
        kw = build_llm_kwargs({"temperature": 0.3, "max_tokens": 2048})
        assert kw["temperature"] == 0.3
        assert kw["max_tokens"] == 2048


class TestApiKeyResolution:
    """网页端配置的 key 必须能绕过环境变量直达客户端。"""

    def test_explicit_key_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
        client = create_llm_client("deepseek", "deepseek-chat", api_key="sk-explicit")
        assert client.resolve_api_key() == "sk-explicit"

    def test_env_used_when_no_explicit_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
        client = create_llm_client("deepseek", "deepseek-chat")
        assert client.resolve_api_key() == "sk-from-env"

    def test_no_key_anywhere_returns_none(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        assert create_llm_client("deepseek", "deepseek-chat").resolve_api_key() is None

    def test_build_llm_kwargs_carries_api_key(self):
        assert build_llm_kwargs({"api_key": "sk-x"})["api_key"] == "sk-x"

    def test_build_llm_kwargs_omits_empty_key(self):
        assert "api_key" not in build_llm_kwargs({"api_key": ""})
        assert "api_key" not in build_llm_kwargs({})

    def test_mock_provider_tolerates_api_key(self):
        # mock 无需 key；多传 api_key 不应炸
        assert create_llm_client("mock", "mock-chat", api_key="sk-x").get_llm() is not None
