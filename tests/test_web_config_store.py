"""网页配置存储测试：掩码、留空保留、白名单、原子写、转运行配置。"""
import json
import os

import pytest

from banalyse.web.config_store import (
    EDITABLE_FIELDS,
    ConfigStore,
    list_providers,
    mask_key,
)


@pytest.fixture
def store(tmp_path):
    """隔离的配置存储，绝不触碰用户真实 ~/.banalyse。"""
    return ConfigStore(path=str(tmp_path / "web_config.json"))


class TestMaskKey:
    def test_long_key_keeps_only_edges(self):
        masked = mask_key("sk-abcdefghijklmnop1234")
        assert masked.startswith("sk-a")
        assert masked.endswith("1234")
        assert "••••••" in masked
        assert masked.count("•") >= 6

    def test_short_key_fully_masked(self):
        assert mask_key("short") == "•••••"
        assert "s" not in mask_key("short").replace("•", "")

    def test_empty_key(self):
        assert mask_key(None) == ""
        assert mask_key("") == ""


class TestSaveAndLoad:
    def test_save_then_masked_hides_plaintext(self, store):
        store.save({"llm_provider": "deepseek", "api_key": "sk-secret-1234567890"})
        masked = store.masked()
        assert masked["llm_provider"] == "deepseek"
        assert masked["api_key_set"] is True
        # 明文绝不出现在对外结构里
        assert "sk-secret-1234567890" not in json.dumps(masked, ensure_ascii=False)

    def test_empty_api_key_keeps_existing(self, store):
        store.save({"api_key": "sk-original-key"})
        store.save({"llm_provider": "qwen"})  # 未带 key
        assert store.load()["api_key"] == "sk-original-key"
        assert store.load()["llm_provider"] == "qwen"

    def test_clear_key_removes_only_key(self, store):
        store.save({"llm_provider": "deepseek", "api_key": "sk-abc"})
        store.clear_key()
        assert "api_key" not in store.load()
        assert store.load()["llm_provider"] == "deepseek"

    def test_whitelist_rejects_unknown_fields(self, store):
        store.save({"llm_provider": "mock", "evil_field": "boom"})
        assert "evil_field" not in store.load()
        assert "evil_field" not in EDITABLE_FIELDS

    def test_reset_clears_everything(self, store):
        store.save({"llm_provider": "deepseek", "api_key": "sk-abc"})
        store.reset()
        assert store.load() == {}

    def test_corrupt_file_degrades_to_empty(self, store, tmp_path):
        with open(store.path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not json")
        assert store.load() == {}          # 坏文件不抛异常
        assert store.masked()["llm_provider"] == "mock"

    def test_write_is_utf8_and_no_leftover_tmp(self, store):
        store.save({"llm_provider": "mock", "output_language": "中文"})
        with open(store.path, encoding="utf-8") as fh:
            assert json.load(fh)["output_language"] == "中文"
        siblings = os.listdir(os.path.dirname(store.path))
        assert not [f for f in siblings if f.endswith(".tmp")]


class TestToRunConfig:
    def test_defaults_models_for_provider(self, store, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        store.save({"llm_provider": "deepseek"})
        cfg = store.to_run_config()
        assert cfg["llm_provider"] == "deepseek"
        assert cfg["quick_think_llm"] == "deepseek-chat"
        assert cfg["deep_think_llm"] == "deepseek-reasoner"
        assert cfg["backend_url"] == "https://api.deepseek.com/v1"
        assert "api_key" not in cfg  # 未配置则不带 key

    def test_explicit_fields_win_over_defaults(self, store):
        store.save({
            "llm_provider": "deepseek",
            "quick_think_llm": "my-quick",
            "backend_url": "https://proxy.local/v1",
            "api_key": "sk-web-key",
        })
        cfg = store.to_run_config()
        assert cfg["quick_think_llm"] == "my-quick"
        assert cfg["backend_url"] == "https://proxy.local/v1"
        assert cfg["api_key"] == "sk-web-key"

    def test_env_key_used_as_fallback(self, store, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
        store.save({"llm_provider": "deepseek"})
        assert store.to_run_config()["api_key"] == "sk-from-env"

    def test_web_key_preferred_over_env(self, store, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
        store.save({"llm_provider": "deepseek", "api_key": "sk-from-web"})
        assert store.to_run_config()["api_key"] == "sk-from-web"

    def test_mock_provider_has_no_key_requirement(self, store):
        store.save({"llm_provider": "mock"})
        cfg = store.to_run_config()
        assert cfg["llm_provider"] == "mock"
        assert "api_key" not in cfg


class TestProviderCatalog:
    def test_lists_mock_and_domestic_vendors(self):
        names = {p["name"] for p in list_providers()}
        assert {"mock", "deepseek", "qwen", "zhipu", "openai", "ollama"} <= names

    def test_requires_key_flags(self):
        by_name = {p["name"]: p for p in list_providers()}
        assert by_name["mock"]["requires_key"] is False
        assert by_name["deepseek"]["requires_key"] is True
        assert by_name["deepseek"]["key_env"] == "DEEPSEEK_API_KEY"
        assert by_name["ollama"]["default_base_url"].startswith("http://localhost")

    def test_every_provider_has_default_models(self):
        for provider in list_providers():
            assert provider["default_deep_model"]
            assert provider["default_quick_model"]
