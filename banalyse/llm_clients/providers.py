"""Provider 注册表：国内外统一声明。

国内厂商大多走 OpenAI 兼容协议 → 底层复用 openai_client，只换 base_url。
新增厂商只需在此登记一行（kind / base_url / env）。"""

# kind 取值：
#   "mock"               离线测试，无需 key（M0 默认）
#   "openai_compatible"  OpenAI 兼容，走 langchain-openai，可配 base_url
#   "native_openai"      原生 OpenAI
#   "native_anthropic"   原生 Anthropic（M3+ 实现）
#   "native_google"      原生 Google（M3+ 实现）

PROVIDER_REGISTRY = {
    # -- 离线 / 本地 --
    "mock": {"kind": "mock", "env": None},
    "ollama": {"kind": "openai_compatible", "base_url": "http://localhost:11434/v1", "env": None},
    # -- 国外 --
    "openai": {"kind": "native_openai", "env": "OPENAI_API_KEY"},
    # -- 国内（OpenAI 兼容）--
    "deepseek": {"kind": "openai_compatible", "base_url": "https://api.deepseek.com/v1", "env": "DEEPSEEK_API_KEY"},
    "qwen": {"kind": "openai_compatible", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "env": "DASHSCOPE_API_KEY"},
    "zhipu": {"kind": "openai_compatible", "base_url": "https://open.bigmodel.cn/api/paas/v4", "env": "ZHIPU_API_KEY"},
}
