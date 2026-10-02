"""模型目录：provider → 建议模型。清单驱动，新增模型在此登记。"""
from .mock_client import MockChatModel

# DEFAULT_MODELS[provider][role]；role ∈ {"deep", "quick"}
DEFAULT_MODELS = {
    "mock": {"deep": "mock-reasoner", "quick": "mock-chat"},
    "deepseek": {"deep": "deepseek-reasoner", "quick": "deepseek-chat"},
    "qwen": {"deep": "qwen-max", "quick": "qwen-plus"},
    "zhipu": {"deep": "glm-4-plus", "quick": "glm-4-flash"},
    "ollama": {"deep": "qwen2.5:14b", "quick": "qwen2.5:7b"},
    "openai": {"deep": "gpt-4o", "quick": "gpt-4o-mini"},
}


def default_model(provider: str, role: str) -> str:
    """返回某 provider 在该角色下的默认模型名。"""
    return DEFAULT_MODELS.get(provider.lower(), {}).get(role, "mock-chat")


KNOWN_MODELS = {m for d in DEFAULT_MODELS.values() for m in d.values()}
KNOWN_MODELS.add(MockChatModel.__name__)
