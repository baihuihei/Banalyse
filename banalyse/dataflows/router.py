"""供应商降级路由：按标的所属市场的供应商链依次尝试，失败返回哨兵。

市场**不再是配置项**，而是从股票代码形态推断出来的（见 ``market.infer_market``）：
纯数字走 A 股链，含字母走海外链。这样用户只需要填一个代码，不必再理解
"这家供应商服务哪个市场"。
"""
import logging
from importlib import import_module

from ..runtime_config import get_config
from .contract import OPTIONAL_CATEGORIES
from .errors import (
    NoDataError,
    VendorError,
    VendorNotConfiguredError,
    VendorRateLimitError,
    data_unavailable_sentinel,
    no_data_sentinel,
)
from .market import infer_market
from .registry import VENDOR_REGISTRY, unconfigured_vendors, vendor_market, vendors_providing

logger = logging.getLogger(__name__)


def _import_callable(vendor: str, method: str):
    package = f"banalyse.dataflows.vendors.{vendor_market(vendor)}.{vendor}.{method}"
    mod = import_module(package)
    return mod.call


def vendor_chain(method: str, symbol: str = "") -> list[str]:
    """按 ``symbol`` 形态推断出的市场，解析可用于 ``method`` 的供应商链。

    链里只保留「配置里点名了、且确实实现了该方法、且 key 已就绪」的供应商，
    顺序即配置顺序（配置顺序 = 优先级）。若该市场没配任何供应商，
    退化为「所有可用供应商」，避免配置缺失直接导致无数据。

    ``symbol`` 缺省为空 → 按 ``global`` 解析（等价于旧版 ``market=global`` 默认）。
    """
    cfg = get_config()
    market = infer_market(symbol)
    requested = list((cfg.get("data_vendors") or {}).get(market) or [])
    available = vendors_providing(method)
    if not requested:
        return available
    return [vendor for vendor in requested if vendor in available]


def route_to_vendor(method: str, *args, **kwargs):
    """按市场供应商链尝试，返回结果；全失败返回哨兵（不抛普通异常）。

    为什么 ``NoDataError`` 也要 ``continue``
    ----------------------------------------
    保留这条链路是刻意的：单源下它退化为"一家失败 → 直接出哨兵"，
    但插槽顺序与降级语义不变，将来再加第二家源（行情/宏观）时不用改路由。
    一个真实场景：同一份财报，公司年报里有，但非年报口径的接口里没有。
    所以所有失败一律继续往下试，最后把**最后一条失败原因**写进哨兵 ——
    排查时能一眼区分"没装库 / 没配 key / 被限流 / 这只票真的没数据"。
    """
    symbol = str(args[0]) if args else "?"
    chain = vendor_chain(method, symbol if args else "")
    last_reason = ""

    for vendor in chain:
        try:
            callable_fn = _import_callable(vendor, method)
            return callable_fn(*args, **kwargs)
        except ImportError as exc:
            logger.warning("vendor %s/%s not importable(%s); skipping", vendor, method, exc)
            last_reason = f"{vendor}: 未安装依赖（{exc}）"
        except VendorNotConfiguredError as exc:
            logger.warning("vendor %s not configured for %s: %s", vendor, method, exc)
            last_reason = f"{vendor}: 未配置（{exc}）"
        except VendorRateLimitError as exc:
            logger.warning("vendor %s rate-limited for %s: %s", vendor, method, exc)
            last_reason = f"{vendor}: 被限流（{exc}）"
        except NoDataError as exc:
            logger.info("vendor %s has no data for %s: %s", vendor, method, exc)
            last_reason = f"{vendor}: 无数据（{exc.detail or exc}）"
        except VendorError as exc:
            logger.warning("vendor %s failed for %s: %s", vendor, method, exc)
            last_reason = f"{vendor}: {exc}"
        except Exception as exc:  # noqa: BLE001
            # 第三方库（requests 等）可能抛任何异常类型。
            # 取数层绝不能把流水线打挂 —— 最坏也只是换下一家供应商。
            logger.warning("vendor %s crashed for %s: %s: %s",
                           vendor, method, type(exc).__name__, exc)
            last_reason = f"{vendor}: {type(exc).__name__}: {exc}"

    # 可优化类别 → 降级哨兵；核心类别 → 明确「不可用」（不中断，交给上层 agent 处理）
    category = _category_of(method)
    detail = last_reason or _no_vendor_reason(method)
    if category in OPTIONAL_CATEGORIES:
        return data_unavailable_sentinel(category, detail)
    return no_data_sentinel(symbol, detail)


def _no_vendor_reason(method: str) -> str:
    """链为空时的可操作诊断。

    只说"没有可用供应商"会让用户无从下手 —— 真正的原因通常是忘配一个环境变量
    （如 ``SEC_EDGAR_USER_AGENT``），或者这个槽位压根没有实现者。分开报出来。
    """
    if not VENDOR_REGISTRY:
        return "未注册任何数据供应商"

    blocked = unconfigured_vendors(method)
    if blocked:
        needs = "、".join(f"{vendor} 需要 {env}" for vendor, env in blocked)
        return f"供应商未就绪：{needs}"

    implemented = any(method in spec.get("provides", []) for spec in VENDOR_REGISTRY.values())
    if not implemented:
        return f"没有任何已注册的供应商实现 {method}（该槽位目前没有数据来源）"
    return f"当前市场未配置提供 {method} 的供应商（检查 data_vendors）"


def _category_of(method: str) -> str:
    from .contract import DATA_METHODS
    m = DATA_METHODS.get(method)
    return m.category if m else "core"
