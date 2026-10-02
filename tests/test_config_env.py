"""配置系统测试。"""
import os

from banalyse.default_config import _ENV_OVERRIDES, DEFAULT_CONFIG, _apply_env_overrides
from banalyse.runtime_config import get_config, run_config


class TestEnvOverrides:
    def test_float_coercion(self, monkeypatch):
        monkeypatch.setenv("BA_TEMPERATURE", "0.2")
        # DEFAULT_CONFIG 中 temperature 默认 0.0（float），据此强转为 float
        cfg = _apply_env_overrides({**DEFAULT_CONFIG})
        assert cfg["temperature"] == 0.2
        assert isinstance(cfg["temperature"], float)

    def test_int_coercion(self, monkeypatch):
        monkeypatch.setenv("BA_MAX_TOKENS", "4096")
        cfg = _apply_env_overrides({**DEFAULT_CONFIG, "max_tokens": 8192})
        assert cfg["max_tokens"] == 4096

    def test_invalid_bool_raises(self):
        import pytest
        cfg = {**DEFAULT_CONFIG, "checkpoint_enabled": False}
        os.environ["BA_CHECKPOINT"] = "treu"  # 拼写错误
        try:
            with pytest.raises(ValueError):
                _apply_env_overrides(cfg)
        finally:
            del os.environ["BA_CHECKPOINT"]

    def test_default_provider_is_mock_for_offline(self):
        assert DEFAULT_CONFIG["llm_provider"] == "mock"


class TestRunConfig:
    def test_contextvar_isolation(self):
        with run_config({"output_language": "English"}):
            assert get_config()["output_language"] == "English"
        # 离开块后恢复默认
        assert get_config()["output_language"] == DEFAULT_CONFIG["output_language"]

    def test_dict_merge_depth_one(self):
        with run_config({"data_vendors": {"global": ["sec_edgar", "x"]}}):
            cfg = get_config()
            assert cfg["data_vendors"]["global"] == ["sec_edgar", "x"]
            # 其它键保持默认（按市场分工：A 股走 AKShare）
            assert cfg["data_vendors"]["china"] == ["akshare"]

    def test_market_is_not_a_config_key(self):
        """市场已改为按代码形态推断，不应再出现在配置里（避免两处真相）。"""
        assert "market" not in DEFAULT_CONFIG
        assert "BA_MARKET" not in _ENV_OVERRIDES


class TestDataLocation:
    """数据目录默认落在「项目内的 .local」，不再占用 C 盘用户主目录。"""

    def test_home_defaults_into_repo_local(self):
        from banalyse.default_config import _PROJECT_HOME, _REPO_ROOT
        assert os.path.join(_REPO_ROOT, ".local") == _PROJECT_HOME
        assert os.path.basename(_PROJECT_HOME) == ".local"

    def test_results_dir_lives_under_project_root(self):
        """报告落盘目录 = 项目下的 record/（可见、可直接翻阅），不再是隐藏的 .local/logs。"""
        from banalyse.default_config import _REPO_ROOT
        assert DEFAULT_CONFIG["results_dir"] == os.path.join(_REPO_ROOT, "record")

    def test_web_config_lives_under_project_home(self):
        from banalyse.default_config import _PROJECT_HOME
        from banalyse.web.config_store import CONFIG_PATH
        assert CONFIG_PATH.startswith(_PROJECT_HOME)

    def test_bf_home_overrides_default(self, tmp_path):
        """BA_HOME 能把整个数据目录搬到别处（子进程隔离，避免 reload 污染）。"""
        import subprocess
        import sys
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {**os.environ, "BA_HOME": str(tmp_path / "custom")}
        proc = subprocess.run(
            [sys.executable, "-c",
             "from banalyse.default_config import _PROJECT_HOME as p; print(p)"],
            capture_output=True, text=True, env=env, cwd=repo, check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == str(tmp_path / "custom")


class TestDotenvLoading:
    """`.env` 必须被真正加载（此前 python-dotenv 只是依赖，从未调用）。"""

    def test_env_file_points_at_repo_root(self):
        import banalyse
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.join(repo, ".env") == banalyse._ENV_FILE

    def test_dotenv_feeds_default_config(self, tmp_path):
        """在临时仓库里放一个 .env，DEFAULT_CONFIG 应读到它。"""
        import shutil
        import subprocess
        import sys
        repo_src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sandbox = tmp_path / "repo"
        (sandbox / "banalyse").mkdir(parents=True)
        for name in ("__init__.py", "default_config.py"):
            shutil.copy2(os.path.join(repo_src, "banalyse", name), sandbox / "banalyse" / name)
        (sandbox / ".env").write_text("BA_OUTPUT_LANGUAGE=English\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-c",
             "from banalyse.default_config import DEFAULT_CONFIG as c; print(c['output_language'])"],
            capture_output=True, text=True, cwd=str(sandbox), check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "English"

    def test_real_env_wins_over_dotenv(self, tmp_path):
        """显式导出的环境变量不应被 .env 覆盖。"""
        import shutil
        import subprocess
        import sys
        repo_src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sandbox = tmp_path / "repo2"
        (sandbox / "banalyse").mkdir(parents=True)
        for name in ("__init__.py", "default_config.py"):
            shutil.copy2(os.path.join(repo_src, "banalyse", name), sandbox / "banalyse" / name)
        (sandbox / ".env").write_text("BA_OUTPUT_LANGUAGE=English\n", encoding="utf-8")
        env = {**os.environ, "BA_OUTPUT_LANGUAGE": "French"}
        proc = subprocess.run(
            [sys.executable, "-c",
             "from banalyse.default_config import DEFAULT_CONFIG as c; print(c['output_language'])"],
            capture_output=True, text=True, cwd=str(sandbox), env=env, check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "French"

