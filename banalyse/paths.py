"""项目目录解析：目录一律以「相对项目根」书写，运行时统一解析为绝对路径。

为什么需要它
------------
本项目要能整目录拷到任意盘符 / 机器直接跑，所以代码里**不出现任何写死的盘符**：
所有目录都相对「项目根」（= 本文件上一级，随仓库一起移动）来定义。

约定
----
- **相对路径** → 相对 **项目根** 解析，与当前工作目录（cwd）无关。
  这样 ``python main.py`` / ``python -m banalyse.web`` / ``pytest`` 从任意目录
  启动，落盘位置都一致（此前 ``data_cache_dir="cache"`` 是 cwd 相对的，换目录启动就落错地方）。
- **绝对路径**（``D:\\data\\...`` / ``/data/...``）→ 原样使用，
  保留「把数据放到项目外」的显式覆盖能力。
- ``~`` → 展开为用户主目录。

用法::

    from .paths import PROJECT_ROOT, resolve

    resolve("record")                 # <项目根>/record
    resolve(cfg["results_dir"])       # 配置里写相对值也能落到项目内
    resolve("D:/data/banalyse/logs")  # 绝对路径原样返回
"""
import os

# 项目根：``banalyse/`` 的上一级（含 main.py / pyproject.toml 的那一层）。
# 用 __file__ 推导而非 cwd，保证「程序在哪被启动」不影响目录定位。
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 默认目录名（相对项目根）。集中定义，避免同名目录散落在各模块里各写一份。
DEFAULT_PROJECT_HOME = ".local"    # 隐藏数据/配置目录（web_config.json 等）
DEFAULT_RESULTS_DIR = "record"     # 分析报告落盘目录（可见，便于直接翻阅）
DEFAULT_CACHE_DIR = "cache"        # 数据缓存目录


def resolve(path: str, *, base: str | None = None) -> str:
    """把「相对项目根」的目录 / 文件路径解析成绝对路径。

    绝对路径与 ``~`` 路径原样（规范化后）返回，因此用户显式指定的
    项目外目录仍然可用；相对路径则锚定到 ``base``（默认项目根），
    不受当前工作目录影响。
    """
    if not path:
        return path
    expanded = os.path.expanduser(str(path))
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    return os.path.normpath(os.path.join(base or PROJECT_ROOT, expanded))


def is_relative(path: str) -> bool:
    """判断路径是否为「相对项目根」的写法（供 UI / 文档提示用）。"""
    if not path:
        return False
    return not os.path.isabs(os.path.expanduser(str(path)))
