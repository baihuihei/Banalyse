"""宏观指标（A 股 / 港股链）：折现基准 = 中国 10 年期国债收益率。

实现委托给共享的 ``vendors/_rates.py`` —— 中美国债在同一张表里，
海外链只是取另一列，没必要两家各写一份。
"""
from ..._rates import long_term_treasury


def call(symbol: str) -> dict:
    """返回该标的市场的长期国债收益率（小数形式）。"""
    return long_term_treasury(symbol)
