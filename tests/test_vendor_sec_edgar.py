"""sec_edgar 供应商的纯函数测试（不打网络）。

重点覆盖两个最容易错的地方：
  · 挑表单：要精确匹配 ``10-K`` 优先，其次才接受 ``10-K/A`` 修订版；
  · XBRL 取数：要筛掉季报、并按最新申报去重（同一期常有原始 + 修订多条）。
"""
from banalyse.dataflows.vendors.foreign.sec_edgar import pick_filing
from banalyse.dataflows.vendors.foreign.sec_edgar.get_filing import html_to_text, trim_by_section
from banalyse.dataflows.vendors.foreign.sec_edgar.get_financials import _annual_map

RECENT = {
    "form": ["10-K/A", "10-K", "8-K"],
    "accessionNumber": ["0001-25-000001", "0001-24-000002", "0001-24-000003"],
    "primaryDocument": ["aa.htm", "bb.htm", "cc.htm"],
    "filingDate": ["2025-03-01", "2024-11-01", "2024-09-01"],
}


class TestPickFiling:
    def test_exact_match_wins_over_amendment(self):
        assert pick_filing(RECENT, "10-K") == ("0001-24-000002", "bb.htm", "2024-11-01")

    def test_falls_back_to_amendment_when_no_exact(self):
        recent = {**RECENT, "form": ["10-K/A", "8-K"]}
        assert pick_filing(recent, "10-K") == ("0001-25-000001", "aa.htm", "2025-03-01")

    def test_def14a_matched(self):
        recent = {**RECENT, "form": ["DEF 14A", "10-K"]}
        assert pick_filing(recent, "DEF 14A")[0] == "0001-25-000001"

    def test_returns_none_when_absent(self):
        assert pick_filing(RECENT, "20-F") is None

    def test_skips_entries_without_document(self):
        recent = {**RECENT, "primaryDocument": ["", "", ""]}
        assert pick_filing(recent, "10-K") is None


class TestXbrlAnnualEntries:
    ANNUAL_2023 = {"start": "2023-01-01", "end": "2023-12-31", "val": 100.0,
                   "form": "10-K", "fp": "FY", "filed": "2024-02-01"}
    ANNUAL_2022 = {"start": "2022-01-01", "end": "2022-12-31", "val": 90.0,
                   "form": "10-K", "fp": "FY", "filed": "2023-02-01"}
    QUARTER = {"start": "2023-07-01", "end": "2023-09-30", "val": 30.0,
               "form": "10-Q", "fp": "Q3", "filed": "2023-10-01"}

    def test_keeps_only_annual_10k_entries(self):
        entries = [self.ANNUAL_2023, self.QUARTER, self.ANNUAL_2022]
        assert _annual_map(entries, "duration") == {2022: 90.0, 2023: 100.0}

    def test_restatement_keeps_latest_filed(self):
        amended = {**self.ANNUAL_2023, "val": 105.0, "filed": "2024-06-01"}
        assert _annual_map([self.ANNUAL_2023, amended], "duration") == {2023: 105.0}

    def test_instant_entries_must_not_have_start(self):
        instant = {"end": "2023-12-31", "val": 500.0, "form": "10-K", "fp": "FY",
                   "filed": "2024-02-01"}
        assert _annual_map([instant], "instant") == {2023: 500.0}
        # 期间科目混进时点查询时要被剔掉
        assert _annual_map([instant, self.ANNUAL_2023], "instant") == {2023: 500.0}

    def test_missing_start_rejected_for_duration(self):
        assert _annual_map([{"end": "2023-12-31", "val": 1.0, "form": "10-K"}],
                           "duration") == {}

    def test_non_numeric_values_dropped(self):
        bad = {**self.ANNUAL_2023, "val": ""}
        assert _annual_map([bad], "duration") == {}


class TestFilingText:
    def test_html_stripped_and_entities_decoded(self):
        text = html_to_text("<html><body><p>Hello&nbsp;World&quot;x&quot;</p></body></html>")
        assert "<" not in text
        assert "Hello World" in text
        assert '"x"' in text

    def test_script_content_removed(self):
        text = html_to_text("<div>keep</div><script>var secret = 1;</script>")
        assert "keep" in text
        assert "secret" not in text

    def test_short_text_is_not_truncated(self):
        text, truncated = trim_by_section("短文本", limit=100)
        assert (text, truncated) == ("短文本", False)

    def test_section_hits_get_priority(self):
        noise = "z" * 180
        wanted = "Item 1. Business " + "y" * 200
        text, truncated = trim_by_section(f"{noise}\n\n{wanted}", limit=250)
        assert truncated is True
        assert "Item 1. Business" in text

    def test_oversized_single_block_is_hard_cut(self):
        text, truncated = trim_by_section("x" * 500, limit=10)
        assert truncated is True
        assert len(text) == 10

    def test_empty_text_is_safe(self):
        assert trim_by_section("", limit=10) == ("", False)
