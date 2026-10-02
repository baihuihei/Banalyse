"""市场推断：用户只填一个代码，不该再选「国内 / 海外」。

这些测试钉住的是**用户可见的契约**：``600519`` 走 A 股链、``AAPL`` 走海外链，
以及"两家供应商只在各自市场的链上出现"。改动 vendor 配置或推断规则时，
这里的失败会直接说明"哪个写法不再被识别"。
"""
import pytest

from banalyse.dataflows import router as router_module
from banalyse.dataflows.market import infer_market, market_label
from banalyse.dataflows.router import vendor_chain
from banalyse.runtime_config import run_config


class TestInferMarket:
    @pytest.mark.parametrize(
        "ticker",
        ["600519", "000001", "300750", "688981", "430047", "920118"],
    )
    def test_pure_digits_are_china(self, ticker):
        assert infer_market(ticker) == "china"

    @pytest.mark.parametrize(
        "ticker",
        ["600519.SS", "000001.SZ", "600519.sh", "430047.BJ", "600519.Sz"],
    )
    def test_a_share_suffix_is_still_china(self, ticker):
        """A 股在 Yahoo 口径下带后缀；不先剥掉就会把 600519.SS 误判成美股。"""
        assert infer_market(ticker) == "china"

    @pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "BRK.A", "TSLA", "googl"])
    def test_letters_are_global(self, ticker):
        assert infer_market(ticker) == "global"

    @pytest.mark.parametrize("ticker", ["", None, "   ", "???"])
    def test_blank_or_unparsable_falls_back_to_global(self, ticker):
        """缺省不能崩：回落到 global（与旧版 market 默认值一致）。"""
        assert infer_market(ticker) == "global"

    def test_label_is_readable_in_report(self):
        assert market_label("china") == "中国 A 股"
        assert market_label("global") == "海外（美股）"

    def test_unknown_label_key_falls_back_to_key(self):
        assert market_label("mars") == "mars"
        assert market_label(None) == ""


class TestChainFollowsTicker:
    """链必须跟着代码走 —— 这是"删掉市场下拉框"之后唯一的选择依据。"""

    CHAIN = {"global": ["sec_edgar"], "china": ["akshare"]}

    @pytest.fixture(autouse=True)
    def _both_available(self, monkeypatch):
        """让两家都"已就绪"，这样断言只反映市场分流，不掺 key/依赖因素。"""
        monkeypatch.setattr(
            router_module, "vendors_providing", lambda method: ["sec_edgar", "akshare"]
        )

    def test_digit_ticker_uses_china_chain(self):
        with run_config({"data_vendors": dict(self.CHAIN)}):
            assert vendor_chain("get_financials", "600519") == ["akshare"]

    def test_letter_ticker_uses_global_chain(self):
        with run_config({"data_vendors": dict(self.CHAIN)}):
            assert vendor_chain("get_financials", "AAPL") == ["sec_edgar"]

    def test_suffixed_a_share_still_uses_china_chain(self):
        with run_config({"data_vendors": dict(self.CHAIN)}):
            assert vendor_chain("get_financials", "600519.SS") == ["akshare"]

    def test_sec_edgar_never_serves_a_china_ticker(self):
        """SEC 没有 A 股申报主体；它出现在 A 股链上只会白试一轮。"""
        with run_config({"data_vendors": dict(self.CHAIN)}):
            assert "sec_edgar" not in vendor_chain("get_financials", "000001")

    def test_no_symbol_falls_back_to_global_chain(self):
        """不带代码的调用（如探活）沿用 global，保持与旧行为一致。"""
        with run_config({"data_vendors": dict(self.CHAIN)}):
            assert vendor_chain("get_financials") == ["sec_edgar"]
