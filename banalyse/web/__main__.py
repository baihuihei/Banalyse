"""启动网页端：``python -m banalyse.web``。

环境变量：
    BA_WEB_HOST  默认 127.0.0.1（仅本机访问；如需局域网改 0.0.0.0）
    BA_WEB_PORT  默认 8000
    BA_WEB_TOKEN 可选口令；设置后需在页面填入 X-Web-Token 才能调用 API
"""
import os

import uvicorn

from .app import create_app


def main() -> None:
    host = os.getenv("BA_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("BA_WEB_PORT", "8000"))
    print(f"\n  Banalyse 网页端 → http://{host}:{port}\n")
    if os.getenv("BA_WEB_TOKEN"):
        print("  已启用 BA_WEB_TOKEN 口令保护\n")
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
