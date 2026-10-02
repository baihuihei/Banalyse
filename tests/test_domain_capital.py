"""确定性资本回报指标测试（ROE/杜邦、ROIC、自由现金流、毛利率、资本开支强度）。

这些数字一律由代码算出，智能体只能引用，因此必须有单测钉死口径。
"""
import pytest

from banalyse.domain.capital import (
    compute_capex_intensity,
    compute_capital_metrics,
    compute_free_cash_flow,
    compute_margins,
    compute_roe,
    compute_roic,
)

FINANCIALS = {
    "revenue": [1000, 1100, 1200],
    "gross_profit": [600, 660, 720],
    "operating_income": [200, 220, 240],
    "net_income": [150, 165, 180],
    "shareholders_equity": [900, 990, 1080],
    "total_assets": [1800, 1950, 2100],
    "total_debt": [200, 200, 200],
    "cash": [100, 100, 100],
    "operating_cash_flow": [220, 240, 260],
    "capital_expenditure": [50, 60, 70],
}


class TestROE:
    def test_latest_uses_average_equity(self):
        res = compute_roe(FINANCIALS)
        # 期末净资产 1080，平均净资产 (1080+990)/2 = 1035
        assert res["latest"] == pytest.approx(180 / 1035, abs=1e-4)
        assert res["years"] == 3

    def test_stable_series_is_consistent(self):
        res = compute_roe(FINANCIALS)
        assert res["trend"] == "stable"
        assert res["consistent"] is True

    def test_dupont_product_reproduces_roe(self):
        res = compute_roe(FINANCIALS)
        dupont = res["dupont"]
        assert dupont["net_margin"] == pytest.approx(180 / 1200, abs=1e-4)
        assert dupont["asset_turnover"] == pytest.approx(1200 / 2100, abs=1e-4)
        assert dupont["equity_multiplier"] == pytest.approx(2100 / 1035, abs=1e-4)
        assert dupont["product"] == pytest.approx(res["latest"], abs=1e-4)

    def test_high_leverage_is_flagged(self):
        assert compute_roe(FINANCIALS)["dupont"]["leverage_driven"] is True

    def test_missing_inputs_reported(self):
        res = compute_roe({"net_income": [10]})
        assert res["available"] is False
        assert "净资产" in res["reason"]


class TestROIC:
    def test_formula_and_wacc_comparison(self):
        res = compute_roic(FINANCIALS, wacc=0.09)
        assert res["available"] is True
        # NOPAT = EBIT 240 * (1 - 25%) = 180
        assert res["nopat"] == pytest.approx(180, abs=1e-4)
        # 投入资本 = 权益 1080 + 有息负债 200 − 现金 100 = 1180
        assert res["invested_capital"] == pytest.approx(1180, abs=1e-4)
        assert res["roic"] == pytest.approx(180 / 1180, abs=1e-4)
        assert res["creates_value"] is True
        assert res["excess_return"] == pytest.approx(180 / 1180 - 0.09, abs=1e-4)

    def test_wacc_is_optional(self):
        res = compute_roic(FINANCIALS)
        assert res["available"] is True
        assert "creates_value" not in res

    def test_explicit_tax_rate_is_used(self):
        res = compute_roic({**FINANCIALS, "tax_rate": 0.15})
        assert res["tax_rate_used"] == 0.15
        assert res["nopat"] == pytest.approx(240 * 0.85, abs=1e-4)

    def test_non_positive_invested_capital_is_rejected(self):
        res = compute_roic({
            "operating_income": [50], "shareholders_equity": [100],
            "total_debt": [0], "cash": [500],
        })
        assert res["available"] is False
        assert "投入资本" in res["reason"]

    def test_missing_ebit_reported(self):
        assert compute_roic({"shareholders_equity": [100]})["available"] is False


class TestFreeCashFlow:
    def test_fcf_and_cash_backing(self):
        res = compute_free_cash_flow(FINANCIALS)
        assert res["fcf"] == pytest.approx(260 - 70, abs=1e-4)
        assert res["fcf_to_net_income"] == pytest.approx(190 / 180, abs=1e-4)
        assert res["cash_backed"] is True

    def test_capex_sign_does_not_matter(self):
        # 资本开支常以负数出现在现金流表，取绝对值后再相减
        res = compute_free_cash_flow({**FINANCIALS, "capital_expenditure": [-50, -60, -70]})
        assert res["fcf"] == pytest.approx(190, abs=1e-4)

    def test_missing_ocf_reported(self):
        assert compute_free_cash_flow({"net_income": [10]})["available"] is False


class TestMarginsAndCapex:
    def test_margin_latest_values(self):
        res = compute_margins(FINANCIALS)
        assert res["gross"]["latest"] == pytest.approx(0.6, abs=1e-4)
        assert res["operating"]["latest"] == pytest.approx(0.2, abs=1e-4)
        assert res["net"]["latest"] == pytest.approx(0.15, abs=1e-4)

    def test_capex_intensity(self):
        res = compute_capex_intensity(FINANCIALS)
        assert res["latest"] == pytest.approx(70 / 1200, abs=1e-4)


class TestAggregate:
    def test_all_blocks_present(self):
        res = compute_capital_metrics(FINANCIALS, wacc=0.09)
        assert res["available"] is True
        assert set(res["metrics"]) == {
            "roe", "roic", "free_cash_flow", "margins", "capex_intensity",
        }
        assert res["data_gaps"] == []

    def test_chinese_aliases_are_understood(self):
        res = compute_capital_metrics({"营业收入": [100], "净利润": [10], "净资产": [100]})
        assert res["metrics"]["roe"]["latest"] == pytest.approx(0.1, abs=1e-4)

    def test_missing_everything_yields_gaps_not_numbers(self):
        res = compute_capital_metrics({})
        assert res["available"] is False
        assert len(res["data_gaps"]) >= 4
        assert all(not block.get("available") for block in res["metrics"].values())

    def test_none_input_is_tolerated(self):
        res = compute_capital_metrics(None)
        assert res["available"] is False
