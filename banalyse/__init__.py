"""Banalyse.

M0 骨架：以 FinRobot 的业务蓝本，用 LangGraph/LangChain 重写。
M0 包含：目录骨架、配置系统、LLM 客户端工厂、可编译的空图、网页端配置界面与测试。
"""
import os

# .env 必须在任何子模块读取环境变量之前加载。
# 包 __init__ 先于 banalyse.default_config 执行，因此 DEFAULT_CONFIG 能读到 .env 里的 BA_*。
# 固定用「项目根目录/.env」而不是从 cwd 逐级向上查找，避免误读上层目录里无关的 .env。
# load_dotenv 默认不覆盖已存在的环境变量，符合「显式导出 > .env」的直觉。
from dotenv import load_dotenv

from .paths import PROJECT_ROOT as _PROJECT_ROOT

_ENV_FILE = os.path.join(_PROJECT_ROOT, ".env")
load_dotenv(_ENV_FILE)

__version__ = "0.1.0"
