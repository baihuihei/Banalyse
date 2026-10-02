"""网页层：把 LLM/数据源配置搬到浏览器，摆脱手改环境变量。

对外暴露 :func:`create_app`（FastAPI 应用工厂）；UI 与 API 同源托管。
"""
from .app import create_app
from .config_store import ConfigStore, list_providers, mask_key

__all__ = ["create_app", "ConfigStore", "list_providers", "mask_key"]
