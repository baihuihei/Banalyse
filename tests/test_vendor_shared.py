"""数据层公共工具测试（离线）。

这些是**跨供应商共用**的底座，错了不会报错、只会让数字悄悄错，
所以单独钉住：``ensure`` 的"空即失败"语义、``to_float`` 的 NaN 过滤、
``align_periods`` 的按年对齐、以及 ticker→路径的清洗。
"""
import pytest

from banalyse.dataflows.errors import NoDataError
from banalyse.dataflows.symbols import safe_ticker_component
from banalyse.dataflows.vendors._shared import align_periods, ensure, to_float


class TestToFloat:
    def test_normal_values(self):
        assert to_float("1.5") == 1.5
        assert to_float(3) == 3.0

    @pytest.mark.parametrize("value", [None, "", "abc", "-", float("nan")])
    def test_junk_becomes_none(self, value):
        assert to_float(value) is None


class TestEnsure:
    def test_empty_payloads_raise(self):
        for empty in ({}, [], "", None):
            with pytest.raises(NoDataError):
                ensure(empty, "AAPL", "sec_edgar", "空")

    def test_non_empty_passes_through(self):
        assert ensure({"a": 1}, "AAPL", "sec_edgar") == {"a": 1}

    def test_detail_is_carried_into_the_error(self):
        with pytest.raises(NoDataError) as excinfo:
            ensure(None, "AAPL", "sec_edgar", "XBRL 未返回年度数据")
        # detail 既作为属性供路由拼捎兵，也写进消息体方便直接看日志
        assert "XBRL 未返回年度数据" in excinfo.value.detail
        assert excinfo.value.detail.startswith("sec_edgar:")   # 带上是谁说的
        assert "XBRL 未返回年度数据" in str(excinfo.value)


class TestAlignPeriods:
    """对齐是按位置算比率的前提：字段年份不齐会把 ROE 算成 188%。"""

    def test_common_years_are_intersected(self):
        aligned, years = align_periods({
            "net_income": {2022: 10.0, 2023: 11.0, 2024: 12.0},
            "equity": {2020: 1.0, 2021: 2.0, 2022: 3.0, 2023: 4.0, 2024: 5.0},
        })
        assert years == [2022, 2023, 2024]
        assert aligned["net_income"] == [10.0, 11.0, 12.0]
        assert aligned["equity"] == [3.0, 4.0, 5.0]

    def test_every_series_ends_up_the_same_length(self):
        aligned, years = align_periods({
            "a": {2023: 1.0, 2024: 2.0},
            "b": {2024: 9.0, 2023: 8.0, 2022: 7.0},
            "c": {2023: 5.0, 2024: 6.0, 2025: 4.0},
        })
        assert years == [2023, 2024]
        assert all(len(series) == len(years) for series in aligned.values())

    def test_years_are_sorted_ascending(self):
        """顺序错方向 = 趋势反着报，比不报还糟。"""
        _, years = align_periods({"a": {2024: 1.0, 2022: 2.0, 2023: 3.0}})
        assert years == [2022, 2023, 2024]

    def test_disjoint_years_fall_back_to_widest_field(self):
        aligned, years = align_periods({
            "a": {2023: 1.0, 2024: 2.0},
            "b": {2010: 5.0},
        })
        assert years == [2023, 2024]
        assert "b" not in aligned        # 覆盖不了基准年份的字段被丢弃，而不是错位
        assert set(aligned) == {"a"}

    def test_empty_input(self):
        assert align_periods({}) == ({}, [])
        assert align_periods({"a": {}}) == ({}, [])


class TestSafeTickerComponent:
    @pytest.mark.parametrize(("raw", "expected"), [
        ("AAPL", "AAPL"),
        ("600519.SS", "600519.SS"),
        ("BRK-B", "BRK-B"),
        ("", "unknown"),
        (None, "unknown"),
    ])
    def test_sanitising(self, raw, expected):
        assert safe_ticker_component(raw) == expected

    def test_path_separators_never_survive(self):
        cleaned = safe_ticker_component("a/b\\c")
        assert "/" not in cleaned and "\\" not in cleaned

    def test_leading_dots_and_underscores_are_stripped(self):
        """``../../etc/passwd`` 必须漱成单层文件名，不能留下任何可上跳的前缀。"""
        cleaned = safe_ticker_component("../../etc/passwd")
        assert cleaned == "etc_passwd"
        assert not cleaned.startswith((".", "_"))
