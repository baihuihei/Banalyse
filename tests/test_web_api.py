"""网页 API 集成测试：全离线（mock provider + 临时目录），验证 key 不外泄。"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from banalyse.agents.dimensions import DIMENSION_ORDER
from banalyse.web import app as app_module
from banalyse.web.app import create_app
from banalyse.web.config_store import ConfigStore

SECRET = "sk-super-secret-1234567890"


@pytest.fixture
def client(tmp_path, offline_evidence):
    app = create_app(store=ConfigStore(path=str(tmp_path / "web_config.json")), require_token=False)
    with TestClient(app) as c:
        yield c


class TestHealthAndCatalog:
    def test_health(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["token_required"] is False

    def test_providers_catalog(self, client):
        providers = client.get("/api/providers").json()["providers"]
        by_name = {p["name"]: p for p in providers}
        assert by_name["deepseek"]["requires_key"] is True
        assert by_name["mock"]["requires_key"] is False
        for p in providers:
            assert {"name", "label", "default_deep_model", "default_quick_model"} <= set(p)


class TestConfigApi:
    def test_get_defaults(self, client):
        body = client.get("/api/config").json()
        assert body["llm_provider"] == "mock"
        assert body["api_key_set"] is False

    def test_put_saves_and_masks(self, client):
        resp = client.put("/api/config", json={"llm_provider": "deepseek", "api_key": SECRET})
        assert resp.status_code == 200
        body = resp.json()
        assert body["api_key_set"] is True
        assert SECRET not in resp.text           # 明文不外泄
        assert "••••••" in body["api_key_masked"]

        # 二次读取仍不泄露
        again = client.get("/api/config")
        assert SECRET not in again.text

    def test_put_empty_key_keeps_existing(self, client):
        client.put("/api/config", json={"api_key": SECRET})
        client.put("/api/config", json={"llm_provider": "qwen"})
        body = client.get("/api/config").json()
        assert body["api_key_set"] is True
        assert body["llm_provider"] == "qwen"

    def test_put_unknown_provider_rejected(self, client):
        resp = client.put("/api/config", json={"llm_provider": "not-real"})
        assert resp.status_code == 400

    def test_put_invalid_temperature_rejected(self, client):
        resp = client.put("/api/config", json={"temperature": 9.9})
        assert resp.status_code == 422

    def test_delete_key(self, client):
        client.put("/api/config", json={"llm_provider": "deepseek", "api_key": SECRET})
        body = client.delete("/api/config/key").json()
        assert body["api_key_set"] is False
        assert body["llm_provider"] == "deepseek"

    def test_reset(self, client):
        client.put("/api/config", json={"llm_provider": "deepseek", "api_key": SECRET})
        body = client.post("/api/config/reset").json()
        assert body["llm_provider"] == "mock"
        assert body["api_key_set"] is False


class TestConnectionApi:
    def test_mock_provider_connects(self, client):
        resp = client.post("/api/config/test", json={"llm_provider": "mock", "prompt": "ping"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["provider"] == "mock"
        assert body["reply"]

    def test_unknown_provider_rejected(self, client):
        resp = client.post("/api/config/test", json={"llm_provider": "not-real"})
        assert resp.status_code == 400

    def test_temp_patch_not_persisted(self, client):
        """「先测再存」：测试用的 key 不应写盘。"""
        client.post("/api/config/test", json={"llm_provider": "mock", "api_key": SECRET})
        assert client.get("/api/config").json()["api_key_set"] is False


class TestReportApi:
    def _point_results_at(self, client, tmp_path):
        client.put("/api/config", json={"results_dir": str(tmp_path / "out")})

    def test_generate_offscreen_mock(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        resp = client.post("/api/reports", json={
            "ticker": "600519",
            "report_date": "2026-09-01",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ticker"] == "600519"
        # 公司名不再是前端输入项：留空时回落到代码本身
        assert body["company_name"] == "600519"
        # 市场由代码形态推断：纯数字 = A 股
        assert body["market"] == "china"
        assert body["provider"] == "mock"
        # 四维度报告齐全，且汇总给出了结论
        assert set(body["reports"]) == set(DIMENSION_ORDER)
        assert body["conclusion"]
        assert body["markdown"]
        assert body["result_path"].endswith(".json")
        assert body["trace"]

    def test_generate_subset_of_dimensions(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        resp = client.post("/api/reports", json={
            "ticker": "AAPL",
            "report_date": "2026-09-01",
            "dimensions": ["business_model", "capital_return"],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 含字母 = 海外市场
        assert body["market"] == "global"
        produced = {k for k, v in body["reports"].items() if (v or "").strip()}
        assert produced == {"business_model", "capital_return"}
        assert "analyst:management" not in body["trace"]

    def test_unknown_dimension_rejected(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        resp = client.post("/api/reports", json={
            "ticker": "AAPL", "report_date": "2026-09-01", "dimensions": ["not-a-dimension"],
        })
        assert resp.status_code == 400

    def test_generated_report_is_readable(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        client.post("/api/reports", json={"ticker": "AAPL", "report_date": "2026-09-01"})
        resp = client.get("/api/reports/AAPL/2026-09-01")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["company"]["ticker"] == "AAPL"
        assert set(payload["reports"]) == set(DIMENSION_ORDER)

    def test_missing_report_404(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        assert client.get("/api/reports/NOPE/1999-01-01").status_code == 404

    def test_traversal_rejected(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        assert client.get("/api/reports/../2026-09-01").status_code in (400, 404)

    def test_missing_ticker_422(self, client):
        assert client.post("/api/reports", json={"report_date": "2026-09-01"}).status_code == 422


class TestTokenGuard:
    def test_401_without_token(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BA_WEB_TOKEN", "s3cret")
        app = create_app(store=ConfigStore(path=str(tmp_path / "c.json")), require_token=True)
        with TestClient(app) as c:
            assert c.get("/api/config").status_code == 401
            ok = c.get("/api/config", headers={"X-Web-Token": "s3cret"})
            assert ok.status_code == 200


class TestNoSecretLeak:
    def test_secret_never_appears_in_any_response(self, client, tmp_path):
        client.put("/api/config", json={
            "llm_provider": "deepseek",
            "api_key": SECRET,
            "results_dir": str(tmp_path / "out"),
        })
        for path in ("/api/config", "/api/providers", "/api/health"):
            assert SECRET not in client.get(path).text, f"leaked at {path}"
        resp = client.post("/api/config/test", json={"llm_provider": "mock"})
        assert SECRET not in resp.text


class TestHistoryApi:
    """生成即落盘 → 中栏初始页的历史列表（代码 / 名称 / 时间）+ 删除。"""

    def _point_results_at(self, client, tmp_path) -> str:
        out = str(tmp_path / "out")
        client.put("/api/config", json={"results_dir": out})
        return out

    def test_history_empty_at_first(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        body = client.get("/api/history").json()
        assert body["count"] == 0
        assert body["reports"] == []
        assert body["dir"] == str(tmp_path / "out")

    def test_generate_saves_and_history_lists_it(self, client, tmp_path):
        out = self._point_results_at(client, tmp_path)
        client.post("/api/reports", json={
            "ticker": "600519", "company": "贵州茅台", "report_date": "2026-09-01",
        })
        client.post("/api/reports", json={
            "ticker": "AAPL", "company": "Apple Inc.", "report_date": "2026-09-02",
        })

        # 每次生成都自动落盘到「项目工作目录」下的 results_dir
        assert os.path.exists(os.path.join(out, "600519", "report_2026-09-01.json"))
        assert os.path.exists(os.path.join(out, "AAPL", "report_2026-09-02.json"))

        body = client.get("/api/history").json()
        assert body["count"] == 2
        by_ticker = {item["ticker"]: item for item in body["reports"]}
        assert set(by_ticker) == {"600519", "AAPL"}
        # 中栏列表要的三件事：代码 / 名称 / 时间
        assert by_ticker["600519"]["name"] == "贵州茅台"
        assert by_ticker["600519"]["report_date"] == "2026-09-01"
        assert by_ticker["AAPL"]["name"] == "Apple Inc."
        assert len(by_ticker["600519"]["saved_at"]) == 19      # YYYY-MM-DD HH:MM:SS
        assert by_ticker["600519"]["market"] == "china"
        assert by_ticker["AAPL"]["market"] == "global"

    def test_history_is_newest_first(self, client, tmp_path):
        out = self._point_results_at(client, tmp_path)
        client.post("/api/reports", json={"ticker": "600519", "report_date": "2026-09-01"})
        client.post("/api/reports", json={"ticker": "AAPL", "report_date": "2026-09-02"})
        # 显式摆好 mtime，避免两次生成落在同一秒导致排序不确定
        os.utime(os.path.join(out, "600519", "report_2026-09-01.json"), (1, 1))
        os.utime(os.path.join(out, "AAPL", "report_2026-09-02.json"), (2, 2))

        reports = client.get("/api/history").json()["reports"]
        assert [item["ticker"] for item in reports] == ["AAPL", "600519"]

    def test_broken_file_still_lists(self, client, tmp_path):
        out = self._point_results_at(client, tmp_path)
        broken_dir = os.path.join(out, "BROKEN")
        os.makedirs(broken_dir, exist_ok=True)
        with open(os.path.join(broken_dir, "report_2026-09-03.json"), "w", encoding="utf-8") as fh:
            fh.write("{ 不是合法 JSON")

        reports = client.get("/api/history").json()["reports"]
        assert len(reports) == 1
        # 读不到 company 就退回目录名 / 文件名，列表不能因此打不开
        assert reports[0]["ticker"] == "BROKEN"
        assert reports[0]["report_date"] == "2026-09-03"

    def test_delete_removes_file_and_empty_folder(self, client, tmp_path):
        out = self._point_results_at(client, tmp_path)
        client.post("/api/reports", json={"ticker": "AAPL", "report_date": "2026-09-02"})

        resp = client.delete("/api/history/AAPL/2026-09-02")
        assert resp.status_code == 200
        assert client.get("/api/history").json()["count"] == 0
        # 文件删掉、空目录也顺手清掉
        assert not os.path.exists(os.path.join(out, "AAPL"))

    def test_delete_missing_404(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        assert client.delete("/api/history/NOPE/1999-01-01").status_code == 404

    def test_delete_traversal_rejected(self, client, tmp_path):
        self._point_results_at(client, tmp_path)
        resp = client.delete("/api/history/..%2F..%2Fetc/2026-09-01")
        assert resp.status_code in (400, 404)

    def test_read_report_falls_back_to_default_dir(self, client):
        """网页配置里没写 results_dir 时，读取接口要回落到项目默认目录，不能 500。"""
        assert client.get("/api/reports/AAPL/2026-09-01").status_code in (200, 404)

    def test_history_falls_back_to_default_dir(self, client, monkeypatch, tmp_path):
        """没配 results_dir 时，历史列表必须扫**项目默认目录**并列出其中已有的报告。

        回归测试：``create_app`` 里 ``@app.get("/api/config") def get_config()``
        这个路由把模块级 import 进来的 ``runtime_config.get_config`` 名字盖掉了，
        于是 ``results_dir()`` 实际调的是那个 HTTP handler——它没有参数，
        返回给前端的配置字典里 ``results_dir`` 恒为 ""。
        结果是列表扫空路径，界面上永远显示"还没有已保存的分析"，
        而磁盘上其实躺着一堆 report_*.json。
        """
        # 在"默认目录"里摆一份报告；不往 /api/config 写 results_dir
        default_dir = tmp_path / "record"
        (default_dir / "AAPL").mkdir(parents=True)
        (default_dir / "AAPL" / "report_2026-09-01.json").write_text(
            json.dumps({"company": {"ticker": "AAPL", "name": "Apple Inc.",
                                    "report_date": "2026-09-01", "market": "us"}}),
            encoding="utf-8",
        )
        # 注意别写成引用 app_module._default_config 的 lambda——monkeypatch 已把
        # 模块里这个名字换成了 lambda 自己，再去取就是无限递归。
        # 先抓住原函数再替换：
        real_default_config = app_module._default_config
        monkeypatch.setattr(
            app_module, "_default_config",
            lambda: {**real_default_config(), "results_dir": str(default_dir)},
        )

        body = client.get("/api/history").json()
        assert body["dir"] == str(default_dir), "回落目录取错，历史列表会扫错地方"
        assert body["count"] == 1
        assert body["reports"][0]["ticker"] == "AAPL"
        assert body["reports"][0]["name"] == "Apple Inc."

