"""AKShare 供应商的纯逻辑测试：**不打网络**。

真实调用已经证明这三件事最容易出错，所以逐条钉住：

  1. **股本取错年份**（实测踩到）：F10 股本结构是"新→旧"排列，按行序取尾部
     会拿到 2001 年上市初期的 1.85 亿股，而茅台真实是 12.5 亿股 —— 市值差 7 倍，
     且方向是"市值被低估 → 显得更便宜"，会直接歪掉安全边际。
  2. **财务字段名匹配**：契约要的是绝对金额科目，而"关键指标"表里只有比率；
     三大报表的科目名还必须精确匹配（"扣非净利润" ≠ "净利润"）。
  3. **三家行情源的列名差异**：东财中文、腾讯/新浪英文，规范化错了就整列丢。
"""
import pandas as pd
import pytest

from banalyse.dataflows.vendors.china.akshare import (
    code_of,
    dotted_code,
    exchange_prefixed,
    latest_share_capital,
)
from banalyse.dataflows.vendors.china.akshare import get_financials as fin
from banalyse.dataflows.vendors.china.akshare import get_price_history as hist


class _FakeAk:
    """只带一个属性的假 akshare 模块，避免测试依赖真实库。"""

    def __init__(self, frame):
        self.stock_zh_a_gbjg_em = lambda **kwargs: frame


class TestSymbolConversion:
    @pytest.mark.parametrize("raw", ["600519", "600519.SS", "sh600519", "SH600519", "600519.SH"])
    def test_all_writings_normalize_to_the_same_code(self, raw):
        assert code_of(raw) == "600519"

    def test_exchange_prefix_for_each_board(self):
        assert exchange_prefixed("600519") == "sh600519"
        assert exchange_prefixed("000001") == "sz000001"
        assert exchange_prefixed("300750") == "sz300750"
        assert exchange_prefixed("688981") == "sh688981"
        assert exchange_prefixed("430047") == "bj430047"

    def test_dotted_form_used_by_eastmoney_f10(self):
        assert dotted_code("600519") == "600519.SH"
        assert dotted_code("000001") == "000001.SZ"

    @pytest.mark.parametrize("raw", ["AAPL", "60051", "6005199", ""])
    def test_non_a_share_code_is_rejected(self, raw):
        from banalyse.dataflows.errors import NoDataError
        with pytest.raises(NoDataError):
            code_of(raw)


class TestLatestShareCapital:
    """回归测试：股本必须取**最新**一条，不能靠行序。"""

    @staticmethod
    def _frame(descending: bool):
        rows = [
            {"变更日期": "2026-05-28", "总股本": 1250081601, "已流通股份": 1250081601},
            {"变更日期": "2025-09-01", "总股本": 1252270215, "已流通股份": 1252270215},
            {"变更日期": "2001-07-31", "总股本": 185000000, "已流通股份": 185000000},
        ]
        return pd.DataFrame(rows if descending else list(reversed(rows)))

    def test_picks_newest_when_sorted_new_first(self):
        total, floating, as_of = latest_share_capital(_FakeAk(self._frame(True)), "600519")
        assert total == 1250081601
        assert floating == 1250081601
        assert as_of == "2026-05-28"

    def test_picks_newest_even_when_sorted_old_first(self):
        """上游哪天把排序倒过来，也不能静默取到 2001 年的 1.85 亿股。"""
        total, _, as_of = latest_share_capital(_FakeAk(self._frame(False)), "600519")
        assert total == 1250081601
        assert as_of == "2026-05-28"

    def test_missing_column_yields_none_instead_of_raising(self):
        assert latest_share_capital(_FakeAk(pd.DataFrame({"别的列": [1]})), "600519") == (
            None, None, None
        )


class TestFinancialFieldMapping:
    @staticmethod
    def _frame():
        # 行序刻意做成"新→旧"，与新浪实际返回一致
        return pd.DataFrame({
            "报告日": ["20251231", "20250630", "20241231", "20051231"],
            "营业总收入": [100.0, 40.0, 90.0, 9.0],
            "营业成本": [10.0, 4.0, 9.0, 1.0],
            "归属于母公司所有者的净利润": [50.0, 20.0, 45.0, 5.0],
            "净利润": [51.0, 21.0, 46.0, 5.5],
            "扣非净利润": [49.0, 19.0, 44.0, 4.9],
        })

    def test_prefers_parent_company_scope(self):
        """归母口径优先 —— 它要跟 shareholders_equity 同源，ROE 才有意义。"""
        frame, dates = fin._annual_rows(self._frame())
        series = fin._series(frame, dates, ("归属于母公司所有者的净利润", "净利润"))
        assert series[2025] == 50.0

    def test_only_annual_rows_survive(self):
        frame, dates = fin._annual_rows(self._frame())
        series = fin._series(frame, dates, ("营业总收入",))
        assert 2024 in series and 2025 in series
        assert set(series) == {2025, 2024, 2005}      # 20250630 被丢掉

    def test_exact_match_never_falls_back_to_similar_name(self):
        """有「扣非净利润」但没有「净利润」时，必须留空而不是拿扣非顶。"""
        frame = pd.DataFrame({
            "报告日": ["20251231"],
            "扣非净利润": [49.0],
        })
        filtered, dates = fin._annual_rows(frame)
        assert fin._series(filtered, dates, ("净利润",)) == {}

    def test_candidates_are_tried_in_order(self):
        frame, dates = fin._annual_rows(self._frame())
        series = fin._series(frame, dates, ("不存在的科目", "营业总收入"))
        assert series == {2025: 100.0, 2024: 90.0, 2005: 9.0}


class TestPriceNormalization:
    """三家上游列名不同：东财中文、腾讯/新浪英文。规范化错了就整列丢。"""

    @staticmethod
    def _frame(columns):
        # 行序刻意做成"新→旧"（与上游一致），normalize 应自行按日期排序
        return pd.DataFrame(dict(zip(columns, [
            ["2026-09-29", "2026-06-01", "2020-01-02"],   # date
            [1235.58, 1281.58, 1000.0],                   # close
            [1245.87, 1290.0, 1010.0],                    # high
        ], strict=True)))

    def test_tencent_columns_are_mapped(self):
        rows = hist._normalize(self._frame(("date", "close", "high")), "腾讯",
                               "20260601", "20260929")
        assert [r["date"] for r in rows] == ["2026-06-01", "2026-09-29"]
        assert rows[-1]["close"] == 1235.58

    def test_eastmoney_columns_are_mapped(self):
        rows = hist._normalize(self._frame(("日期", "收盘", "最高")), "东财",
                               "20260601", "20260929")
        assert [r["date"] for r in rows] == ["2026-06-01", "2026-09-29"]

    def test_window_filter_excludes_out_of_range_rows(self):
        rows = hist._normalize(self._frame(("date", "close", "high")), "新浪",
                               "20260901", "20260930")
        assert [r["date"] for r in rows] == ["2026-09-29"]

    def test_missing_close_column_raises_no_data(self):
        from banalyse.dataflows.errors import NoDataError
        with pytest.raises(NoDataError):
            hist._normalize(pd.DataFrame({"date": ["2026-09-29"]}), "腾讯",
                            "20260601", "20260929")
