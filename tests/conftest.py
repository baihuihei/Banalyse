"""共享 fixtures。"""
import pytest

from banalyse.llm_clients.factory import create_llm_client


@pytest.fixture
def mock_llm():
    """一个可被 LangChain node 调用的 mock LLM（离线）。"""
    return create_llm_client("mock", "mock-chat").get_llm()


@pytest.fixture
def mock_deep_llm():
    return create_llm_client("mock", "mock-reasoner").get_llm()


@pytest.fixture
def offline_evidence(monkeypatch):
    """把取数层钉成哨兵：图 / 网页端测试不得依赖网络。

    两个理由，都是实测过的：
      · 稳定性 —— 供应商会限流、会改字段名，测试不该因此飘红；
      · 速度 —— 不加这道闸，真实供应商的退避重试会让整个套件从 5 秒变成 5 分钟。
    """
    from banalyse.dataflows.contract import DATA_METHODS, OPTIONAL_CATEGORIES
    from banalyse.graph.nodes import collect_evidence

    def fake_route(method: str, *args, **kwargs) -> str:
        category = getattr(DATA_METHODS.get(method), "category", "core")
        if category in OPTIONAL_CATEGORIES:
            return f"DATA_UNAVAILABLE: optional '{category}' 测试环境禁网，不得编造数据。"
        return "NO_DATA_AVAILABLE: 测试环境禁网，不得编造数据。"

    monkeypatch.setattr(collect_evidence, "route_to_vendor", fake_route)
    return fake_route
