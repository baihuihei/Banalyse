"""AKShare 供应商（A 股）—— 补上 SEC 结构上服务不了的那一半。

为什么必须分家
--------------
SEC EDGAR 是**申报文件库**：没有 A 股申报主体，也没有任何交易所行情。
所以纯数字代码在 SEC 链上一个槽位都取不到 —— 这不是配置疏漏，是数据源的
结构性边界。AKShare 补的正是这一块。

代价（实测踩出来的，不是理论担忧）
----------------------------------
AKShare 是**抓取型**聚合库，不是官方 API。实际打接口发现：

  · **东财行情端点（``push2`` / ``push2his``）会持续拒连**
    （``RemoteDisconnected``，连试 4 次全败），而同一家的 ``data.eastmoney.com``
    公告接口、``emweb`` F10 股本接口却完全正常 —— 所以不是"东财挂了"，
    而是**按主机 / 端点**被挡；
  · 雪球接口无 ``xq_a_token`` 直接返回 400016；
  · 上游列名会变，同一含义的中文科目在不同接口里写法不同
    （例：“购建固定资产…**所**支付的现金” vs “支付的现金”）。

因此本包的设计原则是：**任何槽位都不依赖单一上游**。每个槽位按
「东财 → 腾讯 → 新浪」依次尝试（见 :func:`first_frame`），只要有一家给出
数据就算成功；全失败才抛 :class:`NoDataError`。单点被限流不该让整个维度失明。

符号规则（放在供应商自己的包里）
--------------------------------
三家上游对同一个代码有三种口径，各留一个转换函数，不做"万能转换器"：
  ``600519``     → 东财 / 同花顺口径（纯 6 位）
  ``sh600519``   → 新浪 / 腾讯口径（交易所前缀）
  ``600519.SH``  → 东财 F10 口径（点号后缀）
"""
import logging

from ....errors import NoDataError
from ..._shared import require_dependency, to_float

VENDOR = "akshare"

logger = logging.getLogger(__name__)

# 6 位代码 → 交易所：北交所（4/8/92 开头）优先判断，其余按深市 0/2/3 开头区分，
# 剩下的（6/9/5 开头）归上交所。
_BJ_PREFIXES = ("4", "8", "92")
_SZ_PREFIXES = ("0", "2", "3")

# 交易所后缀写法（Yahoo / 东财 F10 口径）
_SUFFIXES = (".SS", ".SZ", ".SH", ".BJ")


def require_akshare():
    """惰性导入 akshare。缺包抛 ImportError —— 这是 router 认得的「跳过这家」信号。

    放在函数里而不是模块顶层，是为了让 ``pip install akshare`` 之前
    整个包仍然可导入：没装依赖和"这家拿不到、换下一家"走同一条代码路径。
    """
    return require_dependency("akshare", VENDOR)


def code_of(symbol: str) -> str:
    """把各种写法的 A 股代码归一化成 6 位数字；不是 A 股代码则抛 NoDataError。"""
    text = str(symbol or "").strip().upper()
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    if len(text) == 8 and text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) != 6:
        raise NoDataError(symbol, f"不是 6 位 A 股代码（解析出 {digits!r}）")
    return digits


def exchange_of(code: str) -> str:
    """6 位代码 → ``sh`` / ``sz`` / ``bj``。"""
    if code.startswith(_BJ_PREFIXES):
        return "bj"
    if code.startswith(_SZ_PREFIXES):
        return "sz"
    return "sh"


def exchange_prefixed(symbol: str) -> str:
    """→ 新浪 / 腾讯口径的 ``sh600519``。"""
    code = code_of(symbol)
    return f"{exchange_of(code)}{code}"


def dotted_code(symbol: str) -> str:
    """→ 东财 F10 口径的 ``600519.SH``。"""
    code = code_of(symbol)
    return f"{code}.{exchange_of(code).upper()}"


def compact_date(value) -> str:
    """``2021-09-01`` → ``20210901``（AKShare 的日期入参口径）。"""
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:8]


def soft(fn, **kwargs):
    """调一个 AKShare 接口；上游限流 / 改版 / 断网一律当作「这个来源没有数据」。

    为什么吞掉异常而不是往上抛：一个槽位往往要问两三个来源，单个来源失败
    不该让整个槽位失败。但**这不允许编造** —— 全部来源都失败时，
    调用方必须抛 :class:`NoDataError`，由 router 转成哨兵。
    """
    try:
        return fn(**kwargs)
    except Exception as exc:  # noqa: BLE001 —— 抓取库会抛各种异常类型
        logger.info("akshare %s failed: %s: %s", getattr(fn, "__name__", fn), type(exc).__name__, exc)
        return None


def is_frame(frame) -> bool:
    """判断是不是一个非空 DataFrame。"""
    return frame is not None and hasattr(frame, "empty") and not frame.empty


def first_frame(attempts) -> tuple:
    """按顺序尝试多个上游，返回 ``(frame, 命中的来源名, 失败来源名列表)``。

    ``attempts`` 是 ``[(来源名, 函数, kwargs), ...]``。这是本包的核心容错手段：
    实测东财行情端点会**持续**拒连，若每个槽位只问一家，那个维度就彻底失明。
    全失败时返回 ``(None, None, [所有来源名])``，由调用方抛 NoDataError。
    """
    failed = []
    for label, fn, kwargs in attempts:
        frame = soft(fn, **kwargs)
        if is_frame(frame):
            return frame, label, failed
        failed.append(label)
    return None, None, failed


def value_at(frame, index: int, *names: str):
    """在宽表（一行一期）里按列名取第 ``index`` 行的数值。

    别名与 :func:`column` 一致：按候选列名依次找，第一个存在的就用。
    取不到返回 None（不抛异常）——缺失就是缺失，不能拿别的列顶。
    """
    series = column(frame, *names)
    if series is None or index >= len(series):
        return None
    return to_float(series.iloc[index])


def column(frame, *names: str):
    """按名取列（上游列名可能微调）；取不到返回 None，不抛异常。"""
    if not is_frame(frame):
        return None
    for name in names:
        if name in frame.columns:
            return frame[name]
    return None


def pick_row(frame, *names: str):
    """在 ``item``/``value`` 长表里按 ``item`` 名精确取第一行；取不到返回 None。"""
    if not is_frame(frame) or "item" not in frame.columns:
        return None
    labels = frame["item"].astype(str)
    for name in names:
        hit = frame[labels == name]
        if not hit.empty:
            return hit.iloc[0]
    return None


def item_text(frame, *names: str):
    """长表里取文本值（不转 float）。"""
    row = pick_row(frame, *names)
    if row is None:
        return None
    raw = row.get("value")
    text = str(raw).strip() if raw is not None else ""
    return text or None


def item_number(frame, *names: str):
    """长表里取数值。"""
    row = pick_row(frame, *names)
    return None if row is None else to_float(row.get("value"))


def latest_share_capital(ak, symbol: str) -> tuple:
    """东财 F10 股本结构 → ``(总股本, 流通股本, 变动日期)``（最新一条）。

    放在公共位置是因为 ``get_quote`` 与 ``get_company_profile`` 都要用它，
    而且它是**实测可用**的股本来源：被挡的是东财 ``push2`` 行情主机，
    ``emweb`` F10 主机正常，所以股本永远有兜底，不会因行情被拒而一起失明。

    **不要依赖行序**。实测这份表是"新→旧"排列，但第一版代码按 `iloc[-1]`
    取"最后一行"，于是拿到 2001 年上市初期的 1.85 亿股 —— 茅台真实总股本是
    12.5 亿股，市值因此差了近 7 倍，而下游会拿这个市值去算安全边际
    （低估市值 = 显得更便宜），是**方向性**的错误。所以这里显式按
    ``变更日期`` 取最新一条；取不到日期时才退回行序。
    """
    frame = soft(ak.stock_zh_a_gbjg_em, symbol=dotted_code(symbol))
    if not is_frame(frame) or "总股本" not in frame.columns:
        return None, None, None

    if "变更日期" in frame.columns:
        # ISO 日期字符串按字典序排序即时间序，无需解析成 datetime
        order = frame.assign(_sort=frame["变更日期"].astype(str)).sort_values("_sort")
    else:
        order = frame
    row = order.iloc[-1]

    total = to_float(row.get("总股本"))
    floating = to_float(row.get("已流通股份")) if "已流通股份" in row.index else None
    changed = row.get("变更日期")
    return total, floating, (str(changed).strip() if changed is not None else None)
