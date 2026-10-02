"""网页端配置持久化：单文件 JSON + 原子写 + API key 掩码。

设计要点
--------
- **密钥不上仓库**：存于项目目录 ``.local/web_config.json``，且文件权限收紧到 0600。
- **永不回传明文**：读接口只回传掩码（``sk-a••••••1234``）与 ``api_key_set`` 标记。
- **留空即保留**：前端提交空 key 表示「不改动」，避免误清空；用「清除」按钮显式删除。
- **白名单写入**：只接受已知字段，防止把任意键写进配置。
- **坏文件不致命**：JSON 解析失败时退化到空配置，不阻断启动。
"""
import contextlib
import json
import os
import tempfile

from ..default_config import _PROJECT_HOME
from ..llm_clients.model_catalog import default_model
from ..llm_clients.providers import PROVIDER_REGISTRY
from ..paths import resolve

CONFIG_PATH = os.path.join(_PROJECT_HOME, "web_config.json")


def default_config_path() -> str:
    """配置落盘位置；可用 ``BA_WEB_CONFIG`` 覆盖（便于多环境/隔离验证）。

    覆盖值可以写相对目录（相对项目根，见 ``paths.resolve``），
    这样 ``.env`` 里不必出现盘符，整目录搬走仍然落在项目内。
    """
    return resolve(os.getenv("BA_WEB_CONFIG") or CONFIG_PATH)

# 允许网页写入的字段白名单
EDITABLE_FIELDS = (
    "llm_provider",
    "api_key",
    "backend_url",
    "deep_think_llm",
    "quick_think_llm",
    "temperature",
    "max_tokens",
    "output_language",
    "results_dir",
)

# provider → 中文展示名（UI 下拉用；缺失则回落到 provider 名）
PROVIDER_LABELS = {
    "mock": "Mock（离线，无需 Key）",
    "ollama": "Ollama（本地部署）",
    "openai": "OpenAI",
    "deepseek": "DeepSeek 深度求索",
    "qwen": "通义千问 Qwen（阿里云）",
    "zhipu": "智谱 GLM",
}

_MASK_DOTS = "••••••"


def mask_key(key: str | None) -> str:
    """把 key 变成可展示的掩码；不泄露中间片段。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{_MASK_DOTS}{key[-4:]}"


def provider_defaults(provider: str) -> dict:
    """某 provider 的默认 base_url / 模型名（用于 UI 自动填充）。"""
    spec = PROVIDER_REGISTRY.get(provider, {})
    return {
        "default_base_url": spec.get("base_url") or "",
        "default_deep_model": default_model(provider, "deep"),
        "default_quick_model": default_model(provider, "quick"),
    }


def list_providers() -> list[dict]:
    """给前端渲染下拉与联动字段的 provider 清单（含是否需 key）。"""
    out = []
    for name, spec in PROVIDER_REGISTRY.items():
        env_name = spec.get("env")
        out.append({
            "name": name,
            "label": PROVIDER_LABELS.get(name, name),
            "kind": spec.get("kind"),
            "requires_key": bool(env_name),
            "key_env": env_name or "",
            # 环境变量里是否已配 key（前端仅作提示，不展示值）
            "key_env_set": bool(env_name and os.getenv(env_name)),
            **provider_defaults(name),
        })
    return out



class ConfigStore:
    """网页配置读写。传 ``path`` 可隔离测试。"""

    def __init__(self, path: str | None = None):
        self.path = path or default_config_path()

    # ---------- 读 ----------
    def load(self) -> dict:
        """读原始配置（含明文 key，仅内部使用）。"""
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}  # 坏文件退化，不阻断启动
        return data if isinstance(data, dict) else {}

    def masked(self) -> dict:
        """返回可安全给前端的配置：key 只以掩码呈现。"""
        data = self.load()
        provider = data.get("llm_provider", "mock")
        spec = PROVIDER_REGISTRY.get(provider, {})
        env_name = spec.get("env")
        return {
            "llm_provider": provider,
            "backend_url": data.get("backend_url", ""),
            "deep_think_llm": data.get("deep_think_llm", ""),
            "quick_think_llm": data.get("quick_think_llm", ""),
            "temperature": data.get("temperature", 0.0),
            "max_tokens": data.get("max_tokens", 8192),
            "output_language": data.get("output_language", "Chinese"),
            "results_dir": data.get("results_dir", ""),
            "api_key_set": bool(data.get("api_key")),
            "api_key_masked": mask_key(data.get("api_key")),
            # 环境变量是否提供 key（用于 UI 提示「将使用环境变量中的 Key」）
            "key_env": env_name or "",
            "key_env_set": bool(env_name and os.getenv(env_name)),
            "stored_at": self.path,
        }


    # ---------- 写 ----------
    def save(self, patch: dict) -> dict:
        """合并保存；空 api_key 视为「保留原值」。"""
        clean = {k: v for k, v in (patch or {}).items() if k in EDITABLE_FIELDS}
        if not clean.get("api_key"):
            clean.pop("api_key", None)  # 留空 = 不改动

        current = self.load()
        current.update(clean)
        self._write(current)
        return current

    def clear_key(self) -> dict:
        """显式删除已存的 key（前端「清除」按钮）。"""
        data = self.load()
        data.pop("api_key", None)
        self._write(data)
        return data

    def reset(self) -> dict:
        """清空整个网页配置。"""
        self._write({})
        return {}

    def _write(self, data: dict) -> None:
        """原子写：临时文件 → os.replace，避免半写坏文件。"""
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".web_config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        self._harden()

    def _harden(self) -> None:
        """尽量收紧权限；Windows 上用户目录本身已有 ACL 保护。"""
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)

    # ---------- 转运行配置 ----------
    def to_run_config(self) -> dict:
        """转成 BanalyseAnalysisGraph 可直接吃的配置（含 api_key）。"""
        data = self.load()
        provider = (data.get("llm_provider") or "mock").lower()
        spec = PROVIDER_REGISTRY.get(provider, {})
        defaults = provider_defaults(provider)

        cfg: dict = {
            "llm_provider": provider,
            "deep_think_llm": data.get("deep_think_llm") or defaults["default_deep_model"],
            "quick_think_llm": data.get("quick_think_llm") or defaults["default_quick_model"],
            "backend_url": data.get("backend_url") or spec.get("base_url"),
            "temperature": float(data.get("temperature", 0.0)),
            "max_tokens": int(data.get("max_tokens", 8192)),
            "output_language": data.get("output_language", "Chinese"),
        }

        # key：网页存的优先，其次回落到环境变量
        key = data.get("api_key")
        env_name = spec.get("env")
        if not key and env_name:
            key = os.getenv(env_name)
        if key:
            cfg["api_key"] = key

        if data.get("results_dir"):
            cfg["results_dir"] = data["results_dir"]
        return cfg
