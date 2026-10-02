"""SEC EDGAR 新增槽位测试（离线）：公司概况 / 总股本 / 8-K 事件 / 原文截断。

夹具用的是**实测抓到的真实结构**（2026-09）：DEI 的
``EntityCommonStockSharesOutstanding`` = 14,594,180,000（与东财 f84 一致）、
``EntityPublicFloat`` = 3.25e12、SIC 3571 Electronic Computers、8-K item ``"2.02,9.01"``。
"""
import json

import pytest

from banalyse.dataflows.errors import NoDataError
from banalyse.dataflows.vendors.foreign import sec_edgar as sec
from banalyse.dataflows.vendors.foreign.sec_edgar.get_company_profile import call as profile_call
from banalyse.dataflows.vendors.foreign.sec_edgar.get_filing import call as filing_call
from banalyse.dataflows.vendors.foreign.sec_edgar.get_news import call as news_call
from banalyse.dataflows.vendors.foreign.sec_edgar.get_news import decode_items
from banalyse.dataflows.vendors.foreign.sec_edgar.get_quote import call as quote_call

CIK = "0000320193"


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeHttp:
    """按 URL 子串路由的假会话，同时记录请求过的 URL。"""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        for fragment, payload in self.routes.items():
            if fragment in url:
                return payload if isinstance(payload, FakeResponse) else FakeResponse(payload)
        raise AssertionError("unexpected url: " + url)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


TICKER_TABLE = {"0": {"ticker": "AAPL", "cik_str": 320193}}

SUBMISSIONS = {
    "cik": CIK,
    "name": "Apple Inc.",
    "entityType": "operating",
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "stateOfIncorporation": "CA",
    "stateOfIncorporationDescription": "CA",
    "fiscalYearEnd": "0926",
    "tickers": ["AAPL"],
    "exchanges": ["Nasdaq"],
    "ein": "942404110",
    "lei": "HWUPKR0MPOU8FGXBT394",
    "category": "Large accelerated filer",
    "website": "https://www.apple.com",
    "formerNames": [{"name": "APPLE COMPUTER INC", "from": "1994-01-26", "to": "2007-01-09"}],
    "addresses": {"business": {"city": "CUPERTINO", "stateOrCountry": "CA",
                               "stateOrCountryDescription": "CA",
                               "street1": "ONE APPLE PARK WAY"}},
    "filings": {
        "recent": {
            "accessionNumber": ["0000320193-26-000010", "0000320193-26-000011",
                                "0000320193-25-000079"],
            "filingDate": ["2026-09-01", "2026-07-30", "2025-10-31"],
            "reportDate": ["2026-08-28", "2026-07-25", "2025-09-27"],
            "form": ["8-K", "8-K", "10-K"],
            "primaryDocument": ["aa8k.htm", "bb8k.htm", "aa10k.htm"],
            "primaryDocDescription": ["8-K", "8-K", "10-K"],
            "items": ["5.02", "2.02,9.01", ""],
        }
    },
}

COMPANYFACTS = {
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {"shares": [
                    {"end": "2025-07-18", "val": 15000000000, "form": "10-Q",
                     "filed": "2025-08-01", "fp": "Q3"},
                    {"end": "2026-07-17", "val": 14594180000, "form": "10-Q",
                     "filed": "2026-07-31", "fp": "Q3"},
                ]}
            },
            "EntityPublicFloat": {
                "units": {"USD": [
                    {"end": "2025-03-28", "val": 3253431000000, "form": "10-K",
                     "filed": "2025-10-31"},
                ]}
            },
        },
        "us-gaap": {
            "Assets": {"units": {"USD": [
                {"end": "2024-09-28", "val": 364980000000, "form": "10-K",
                 "filed": "2024-11-01", "fp": "FY"},
            ]}},
        },
    }
}


@pytest.fixture(autouse=True)
def _clear_sec_caches():
    sec._tickers_cache["data"] = None
    sec._facts_cache.clear()
    yield
    sec._tickers_cache["data"] = None
    sec._facts_cache.clear()


@pytest.fixture
def install(monkeypatch):
    """把 sec_edgar 的会话整个换成假 HTTP。"""
    def _install(routes):
        http = FakeHttp({"company_tickers.json": TICKER_TABLE, **routes})
        monkeypatch.setattr(sec, "session", lambda: http)
        return http
    return _install


class TestLatestDei:
    def test_picks_the_most_recent_reporting_date(self):
        value, end, form, filed = sec.latest_dei(
            COMPANYFACTS, "EntityCommonStockSharesOutstanding", units=("shares",))
        assert value == 14594180000.0
        assert end == "2026-07-17"
        assert form == "10-Q"

    def test_missing_tag_returns_none_tuple(self):
        assert sec.latest_dei(COMPANYFACTS, "NoSuchTag") == (None, None, None, None)


class TestRecentFilings:
    def test_parallel_lists_become_rows(self):
        rows = sec.recent_filings(SUBMISSIONS["filings"]["recent"])
        assert len(rows) == 3
        assert rows[0]["form"] == "8-K"
        assert rows[2]["items"] == ""

    def test_mismatched_lengths_are_tolerated(self):
        """某一列比其它列短时按最短的取，不抛异常。"""
        rows = sec.recent_filings({
            "form": ["10-K", "8-K"],
            "filingDate": ["2024-01-01", "2024-02-02"],
            "reportDate": ["2023-12-31", "2024-01-31"],
            "accessionNumber": ["a"],          # 只有一条
            "primaryDocument": ["d"],
            "primaryDocDescription": ["10-K"],
            "items": [""],
        })
        assert len(rows) == 1
        assert rows[0]["form"] == "10-K"

    def test_missing_column_yields_no_rows(self):
        """整个列都缺 = 数据不完整，宁可返回空也不要下游拿到 None 拼出坏 URL。"""
        assert sec.recent_filings({"form": ["10-K"]}) == []


class TestCompanyProfile:
    def test_metadata_is_surfaced(self, install):
        install({"submissions/CIK": SUBMISSIONS})
        profile = profile_call("AAPL")
        assert profile["name"] == "Apple Inc."
        assert profile["sic"] == "3571"
        assert profile["sicDescription"] == "Electronic Computers"
        assert profile["stateOfIncorporation"] == "CA"
        assert profile["fiscalYearEnd"] == "0926"
        assert profile["cik"] == CIK

    def test_former_names_and_city_are_kept(self, install):
        install({"submissions/CIK": SUBMISSIONS})
        profile = profile_call("AAPL")
        assert profile["formerNames"][0]["name"] == "APPLE COMPUTER INC"
        assert profile["businessAddress"] == {"city": "CUPERTINO", "stateOrCountry": "CA",
                                              "stateOrCountryDescription": "CA"}

    def test_street_address_is_dropped(self, install):
        install({"submissions/CIK": SUBMISSIONS})
        assert "street1" not in json.dumps(profile_call("AAPL"))


class TestSecQuote:
    def test_shares_come_from_dei_cover_page(self, install):
        install({"companyfacts": COMPANYFACTS})
        out = quote_call("AAPL")
        assert out["shares"] == 14594180000.0
        assert out["shares_as_of"] == "2026-07-17"

    def test_price_is_deliberately_absent(self, install):
        """SEC 不含行情。price 必须是 None —— 绝不能用封面页陈旧数字冒充现价。"""
        install({"companyfacts": COMPANYFACTS})
        out = quote_call("AAPL")
        assert out["price"] is None
        assert out["market_cap"] is None
        assert "SEC 不含行情" in out["note"]

    def test_public_float_is_an_anchor_not_a_price(self, install):
        install({"companyfacts": COMPANYFACTS})
        anchor = quote_call("AAPL")["public_float"]
        assert anchor["public_float"] == 3253431000000.0
        assert anchor["as_of"] == "2025-03-28"
        assert anchor["implied_price"] == pytest.approx(
            3253431000000.0 / 14594180000.0, abs=1e-4)
        assert "不得当作当前股价使用" in anchor["caveat"]

    def test_no_dei_data_raises_no_data(self, install):
        install({"companyfacts": {"facts": {"dei": {}}}})
        with pytest.raises(NoDataError):
            quote_call("AAPL")


class TestSecNews:
    def test_only_8k_forms_are_returned(self, install):
        install({"submissions/CIK": SUBMISSIONS})
        events = news_call("AAPL")["events"]
        assert [e["date"] for e in events] == ["2026-09-01", "2026-07-30"]
        assert all(e["form"].startswith("8-K") for e in events)

    def test_item_codes_are_decoded(self, install):
        install({"submissions/CIK": SUBMISSIONS})
        first, second = news_call("AAPL")["events"]
        assert first["items"] == [{"code": "5.02", "label": "董监高变动"}]
        assert second["items"][0]["label"] == "业绩发布（经营成果与财务状况）"
        assert second["items"][1]["code"] == "9.01"

    def test_material_events_are_flagged(self, install):
        """5.02（高管变动）属重大；2.02（业绩发布）属常规。"""
        install({"submissions/CIK": SUBMISSIONS})
        out = news_call("AAPL")
        assert out["events"][0]["material"] is True
        assert out["events"][1]["material"] is False
        assert out["material_count"] == 1

    def test_unknown_item_code_is_kept_raw(self):
        assert decode_items("1.01,99.99")[1] == {"code": "99.99", "label": "未收录的 item 代码"}

    def test_empty_items_string(self):
        assert decode_items("") == []
        assert decode_items(None) == []

    def test_no_8k_at_all_raises_no_data(self, install):
        install({"submissions/CIK": {"name": "X", "filings": {"recent": {
            "form": ["10-K"], "filingDate": ["2025-01-01"],
            "accessionNumber": ["a"], "primaryDocument": ["d"], "items": [""],
        }}}})
        with pytest.raises(NoDataError):
            news_call("AAPL")


class TestRawFiling:
    def test_filing_is_trimmed_and_flagged(self, install):
        install({
            "submissions/CIK": SUBMISSIONS,
            "Archives": FakeResponse(
                text="<html><body><p>Item 1. Business</p><p>"
                     + "正文内容 " * 20000 + "</p></body></html>"),
        })
        out = filing_call("AAPL", "10-K")
        assert out["form"] == "10-K"
        assert out["filed"] == "2025-10-31"
        assert out["truncated"] is True
        assert out["chars"] <= 60_000
        assert "正文内容" in out["text"]

    def test_missing_form_raises_no_data(self, install):
        install({"submissions/CIK": SUBMISSIONS})
        with pytest.raises(NoDataError):
            filing_call("AAPL", "20-F")

    def test_companyfacts_is_downloaded_once_per_run(self, install):
        """companyfacts 十几 MB，get_financials 与 get_quote 必须共用同一份。"""
        http = install({"companyfacts": COMPANYFACTS})
        quote_call("AAPL")
        quote_call("AAPL")
        facts_hits = [url for url in http.requested if "companyfacts" in url]
        assert len(facts_hits) == 1
