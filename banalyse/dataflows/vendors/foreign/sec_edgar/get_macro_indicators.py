"""宏观指标（美股链）：折现基准 = 美国 10 年期国债收益率。

实现委托给共享的 ``vendors/_rates.py``。放在海外链里而不是新建第三方源，
是因为「按市场取对应国债」本来就是一条规则的两半，链走哪条就该拿哪国的利率。
"""
from ..._rates import long_term_treasury


def call(symbol: str) -> dict:
    """返回该标的市场的长期国债收益率（小数形式）。"""
    return long_term_treasury(symbol)
