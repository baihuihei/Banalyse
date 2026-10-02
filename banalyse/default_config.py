"""配置唯一真相来源 + 环境变量(BA_*) → 配置键 的映射表。

清单驱动：想暴露一个新的可环境变量覆盖的配置，只在这里加一行。
"""
import os

from .paths import (
    DEFAULT_CACHE_DIR,
    DEFAULT_PROJECT_HOME,
    DEFAULT_RESULTS_DIR,
    PROJECT_ROOT,
    resolve,
)

# 项目根：随仓库移动而移动，代码里不出现任何写死的盘符（见 paths.py）。
_REPO_ROOT = PROJECT_ROOT  # 兼容旧引用名
# 默认数据/配置目录：相对项目根解析成「项目目录/.local」。
# 可用 BA_HOME 覆盖；写相对值 = 相对项目根，写绝对路径 = 原样使用。
_PROJECT_HOME = resolve(os.getenv("BA_HOME") or DEFAULT_PROJECT_HOME)

# env-var → config-key。值类型由默认值推导（bool/int/float/str）。
_ENV_OVERRIDES = {
    "BA_LLM_PROVIDER":     "llm_provider",
    "BA_DEEP_THINK_LLM":   "deep_think_llm",
    "BA_QUICK_THINK_LLM":  "quick_think_llm",
    "BA_BACKEND_URL":      "backend_url",
    "BA_OUTPUT_LANGUAGE":  "output_language",
    "BA_TEMPERATURE":      "temperature",
    "BA_MAX_TOKENS":       "max_tokens",
    "BA_CHECKPOINT":       "checkpoint_enabled",
    "BA_RESULTS_DIR":      "results_dir",
}

_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")

# 供应商链单独处理（值是逗号分隔的列表，不能用标量强转）
_DATA_VENDOR_ENV = {
    "BA_DATA_VENDORS_GLOBAL": "global",
    "BA_DATA_VENDORS_CHINA": "china",
}


def _coerce(value: str, reference):
    """把 env 字符串强转为默认值的类型；非法值抛错，避免静默错配。"""
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc

    # 供应商链：BA_DATA_VENDORS_GLOBAL=sec_edgar（逗号分隔，顺序即优先级）
    vendors = None
    for env_var, market in _DATA_VENDOR_ENV.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        if vendors is None:      # 先复制，避免改动共享的嵌套 dict
            vendors = dict(config.get("data_vendors") or {})
        vendors[market] = [name.strip() for name in raw.split(",") if name.strip()]
    if vendors is not None:
        config["data_vendors"] = vendors

    return config


DEFAULT_CONFIG = _apply_env_overrides({
    # ===== LLM =====
    # M0 默认 mock：离线可跑通。接入真实模型改 env：BA_LLM_PROVIDER=deepseek 等。
    "llm_provider": os.getenv("BA_LLM_PROVIDER", "mock"),
    "deep_think_llm": os.getenv("BA_DEEP_THINK_LLM", "mock-reasoner"),
    "quick_think_llm": os.getenv("BA_QUICK_THINK_LLM", "mock-chat"),
    "backend_url": None,
    "temperature": 0.0,
    "max_tokens": 8192,
    "output_language": "Chinese",
    # ===== 运行 =====
    # 市场不是配置项：由股票代码形态推断（纯数字=A 股，含字母=海外），
    # 见 dataflows/market.infer_market。
    # 参与分析的维度（清单驱动；见 agents/dimensions.py）
    "dimensions": ["business_model", "management", "capital_return", "margin_of_safety"],
    "max_recur_limit": 100,
    "checkpoint_enabled": False,
    "max_dispatch_attempts": 2,    # 主管对同一维度最多派活次数（防死循环）
    # ===== 估值假设（确定性计算的输入；LLM 不得篡改） =====
    "valuation_assumptions": {
        "wacc": 0.09,              # 资本成本，用于与 ROIC 比较
    },
    "valuation_scenarios": {
        "pessimistic": {"discount_rate": 0.11, "growth_rate": 0.00, "terminal_growth": 0.015},
        "base": {"discount_rate": 0.09, "growth_rate": 0.05, "terminal_growth": 0.025},
        "optimistic": {"discount_rate": 0.08, "growth_rate": 0.10, "terminal_growth": 0.035},
    },
    # 折现率锚定：能取到该市场的长期国债收益率时，折现率 = 国债 + 股权风险溢价，
    # 情景再加减 spread（A 股/港股用中国国债，美股用美国国债；见 dataflows/vendors/_rates.py）。
    # 取不到才退回上面 valuation_scenarios 里写死的费率。
    "valuation_discount": {
        "equity_risk_premium": 0.05,
        "scenario_spread": {"pessimistic": 0.02, "base": 0.0, "optimistic": -0.01},
    },
    "valuation_years": 10,             # 显式预测年数
    "required_margin_of_safety": 0.30,  # 要求的安全边际（对最保守情景判定）
    "valuation_sensitivity": {
        "discount_rates": [0.08, 0.09, 0.10, 0.11, 0.12],
        "terminal_growths": [0.015, 0.02, 0.025, 0.03],
    },
    # ===== 路径（一律写相对项目根的目录，见 paths.py；绝对路径也支持）=====
    # 报告落盘根目录：项目下的 record/（看得见、便于直接翻阅与备份），
    # 而不是 .local/logs 那个隐藏目录——生成的分析要能被人找到。
    # 仍可用 BA_RESULTS_DIR 覆盖；写相对值 = 相对项目根，写绝对路径 = 原样使用。
    "results_dir": os.getenv("BA_RESULTS_DIR") or DEFAULT_RESULTS_DIR,
    "data_cache_dir": DEFAULT_CACHE_DIR,
    # ===== 数据供应商：按市场分工 =====
    # 市场由代码形态推断，链里只列**该市场**的供应商：
    #   纯数字（如 600519 / 600519.SS）→ china → AKShare
    #   含字母（如 AAPL / MSFT）      → global → SEC EDGAR
    #
    # 为什么必须分家
    #   · SEC EDGAR 没有 A 股申报主体，A 股标的在它那里一个槽位都取不到；
    #   · SEC EDGAR 结构上不含交易所行情，所以 A 股的现价只能靠 AKShare；
    #   · AKShare 是抓取型数据源（东财/新浪/同花顺），限流与封 IP 的风险
    #     不适合再叠加到已经很稳的 SEC 链上。
    #
    # AKShare 需要额外安装：``pip install akshare``。没装时链不会断，
    # 路由会把 ImportError 归为"该供应商不可用"并在哨兵里点名缺哪个包。
    # SEC EDGAR 的前置条件：``.env`` 里必须配 ``SEC_EDGAR_USER_AGENT``。
    "data_vendors": {
        "global": ["sec_edgar"],
        "china": ["akshare"],
    },
})
