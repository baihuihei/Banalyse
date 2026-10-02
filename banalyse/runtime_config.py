"""运行期配置：ContextVar 隔离，多任务并发互不污染。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from .default_config import DEFAULT_CONFIG

_run_config: ContextVar[dict | None] = ContextVar("banalyse_run_config", default=None)


def _merge(base: dict, config: dict) -> dict:
    """dict 值一层深度合并，标量直接覆盖。"""
    out = deepcopy(base)
    for key, value in (config or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


@contextmanager
def run_config(overrides: dict | None = None):
    """把本次运行的配置绑定到 ContextVar；块内所有读取共享。"""
    merged = _merge(DEFAULT_CONFIG, overrides)
    token = _run_config.set(merged)
    try:
        yield
    finally:
        _run_config.reset(token)


def get_config() -> dict:
    """当前运行的配置；不在运行块内时返回默认。"""
    scoped = _run_config.get()
    return deepcopy(scoped) if scoped is not None else deepcopy(DEFAULT_CONFIG)
