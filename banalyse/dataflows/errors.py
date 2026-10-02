"""类型化异常 + 哨兵文本。所有说给 LLM 的「无数据」都走哨兵，禁止编造。"""


class VendorError(Exception):
    """数据供应商相关错误基类。"""


class NoDataError(VendorError):
    """该供应商对这只标的没有数据。

    ``detail`` 同时写进消息体：否则日志里只剩 "no data for 'AAPL'"，
    排查时看不出到底是"真没数据"还是"这只票不在覆盖范围"。
    """

    def __init__(self, symbol: str, detail: str = ""):
        message = f"no data for '{symbol}'"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
        self.symbol = symbol
        self.detail = detail


class VendorNotConfiguredError(VendorError):
    """供应商缺少必需 API key。"""


class VendorRateLimitError(VendorError):
    """供应商限流。"""


def no_data_sentinel(symbol: str, detail: str = "") -> str:
    """明确的「无数据」哨兵文本，指令 LLM 如实报告、不得编造。"""
    suffix = f" ({detail})" if detail else ""
    return (
        f"NO_DATA_AVAILABLE: no usable data for '{symbol}'{suffix}. "
        "Do not estimate or fabricate values — report data as unavailable."
    )


def data_unavailable_sentinel(category: str, detail: str = "") -> str:
    """可优化类别数据不可用的哨兵；LLM 应跳过该维度。"""
    suffix = f" ({detail})" if detail else ""
    return (
        f"DATA_UNAVAILABLE: optional '{category}' could not be retrieved{suffix}. "
        "Proceed without it; do not fabricate values."
    )
