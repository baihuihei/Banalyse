"""服务端集成验证：真实 FastAPI 路由返回的页面/静态资源是否带上本次改动。

用法：python scripts/check_web_integration.py
项目根按本文件位置推导（scripts/ 的上一级），换机器/换盘符都能跑。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from banalyse.web.app import create_app
from banalyse.web.config_store import ConfigStore

with tempfile.TemporaryDirectory() as tmp:
    app = create_app(store=ConfigStore(path=os.path.join(tmp, "c.json")), require_token=False)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200, page.status_code
        html = page.text

        checks = {
            "页面已无信息框卡片": 'id="open-dims"' not in html and 'id="close-dims"' not in html,
            "页面含四个框容器": 'id="dims-intro"' in html and 'id="dims-grid"' in html,
            "四个框默认常驻（无 hidden）": 'id="dims-intro"' in html and 'id="dims-intro" hidden' not in html,
            "页面含左栏保存按钮": 'id="save-report"' in html and 'id="save-action"' in html,
            "保存区默认收起": 'id="save-action" hidden' in html,
            "静态资源带版本戳": "/static/app.js?v=" in html and "/static/style.css?v=" in html,
            "页面不被缓存": page.headers.get("cache-control") == "no-cache, must-revalidate",
        }

        js = client.get("/static/app.js")
        css = client.get("/static/style.css")
        checks["app.js 可访问"] = js.status_code == 200
        checks["style.css 可访问"] = css.status_code == 200
        checks["app.js 含保存逻辑"] = "function saveReport()" in js.text and "syncSaveAction" in js.text
        checks["app.js 含四个框渲染"] = "function buildDimsIntro()" in js.text
        checks["app.js 已删掉 showDimsIntro"] = "showDimsIntro" not in js.text
        checks["style.css 含新样式"] = ".dims-grid {" in css.text and ".history-item {" in css.text
        checks["style.css 已删掉 .intro-card"] = ".intro-card" not in css.text

        health = client.get("/api/health").json()
        checks["健康检查正常"] = health["status"] == "ok"

        failed = 0
        for name, passed in checks.items():
            failed += 0 if passed else 1
            print(f"{'PASS' if passed else 'FAIL'}  {name}")
        print(f"\n{len(checks) - failed}/{len(checks)} passed")
        sys.exit(1 if failed else 0)
