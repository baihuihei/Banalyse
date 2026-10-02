"""确定性估值单元测试（三情景 DCF / 敏感性 / 安全边际区间）。"""
import pytest

from banalyse.domain.valuation import (
    compute_sensitivity,
    compute_valuation,
    intrinsic_value,
    owner_earnings_from,
    project,
)


def _capital_with_fcf(fcf: float = 100.0) -> dict:
    """构造「资本回报指标」形态的输入，只有自由现金流是折现基数。"""
    return {"available": True, "metrics": {"free_cash_flow": {"available": True, "fcf": fcf}}}


class TestPureMath:
    def test_project_compounds_from_year_one(self):
        assert project(100.0, 0.10, 3) == pytest.approx([110.0, 121.0, 133.1])

    def test_intrinsic_value_rejects_rate_below_terminal_growth(self):
        try:
            intrinsic_value(100.0, {
                "discount_rate": 0.02, "growth_rate": 0.0,
                "terminal_growth": 0.03, "years": 5,
            })
        except ValueError as exc:
            assert "折现率" in str(exc)
        else:  # pragma: no cover - 参数非法时必须抛出
            raise AssertionError("折现率 <= 永续增长率时应当抛错")

    def test_owner_earnings_taken_from_free_cash_flow(self):
        assert owner_earnings_from(_capital_with_fcf(123.0)) == 123.0
        assert owner_earnings_from({}) is None


class TestThreeScenarios:
    def test_produces_full_scenario_set_and_range(self):
        res = compute_valuation(_capital_with_fcf(), price=10.0, shares=50.0)
        assert res["available"] is True
        assert set(res["scenarios"]) == {"pessimistic", "base", "optimistic"}
        assert res["intrinsic_range"]["low"] < res["intrinsic_range"]["high"]
        # 悲观情景的内在价值必须低于乐观情景（假设本身就分化）
        assert (
            res["scenarios"]["pessimistic"]["intrinsic_value"]
            < res["scenarios"]["optimistic"]["intrinsic_value"]
        )

    def test_missing_free_cash_flow_basis_is_declared_not_faked(self):
        res = compute_valuation({})
        assert res["available"] is False
        assert "自由现金流" in res["reason"]

    def test_non_positive_basis_is_rejected(self):
        res = compute_valuation(_capital_with_fcf(0.0))
        assert res["available"] is False

    def test_invalid_scenario_parameters_marked_unavailable(self):
        res = compute_valuation(
            _capital_with_fcf(),
            scenarios={"pessimistic": {"discount_rate": 0.01, "growth_rate": 0.0,
                                       "terminal_growth": 0.03}},
        )
        assert res["scenarios"]["pessimistic"]["available"] is False
        # 其余情景不受影响
        assert res["scenarios"]["base"]["available"] is True


class TestSafetyMargin:
    def test_margin_is_negative_when_market_price_is_rich(self):
        res = compute_valuation(_capital_with_fcf(10.0), price=1000.0, shares=1.0)
        assert res["conservative_margin"] < 0
        assert res["meets_required_margin"] is False

    def test_margin_is_positive_when_market_price_is_cheap(self):
        res = compute_valuation(_capital_with_fcf(100.0), price=1.0, shares=1.0)
        assert res["conservative_margin"] > 0
        assert res["meets_required_margin"] is True

    def test_missing_price_or_shares_becomes_data_gap(self):
        res = compute_valuation(_capital_with_fcf())
        assert res["available"] is True
        assert res["market"] is None
        assert res["margin_of_safety"] is None
        assert res["data_gaps"]

    def test_all_scenarios_get_per_share_value(self):
        res = compute_valuation(_capital_with_fcf(), price=10.0, shares=50.0)
        assert set(res["intrinsic_value_per_share"]) == {"pessimistic", "base", "optimistic"}
        assert all(v > 0 for v in res["intrinsic_value_per_share"].values())


class TestSensitivity:
    def test_grid_matches_declared_axes(self):
        sens = compute_sensitivity(100.0, 10, {
            "discount_rates": [0.08, 0.09],
            "terminal_growths": [0.015, 0.02, 0.025],
        })
        assert sens["discount_rates"] == [0.08, 0.09]
        assert sens["terminal_growths"] == [0.015, 0.02, 0.025]
        assert len(sens["grid"]) == 2
        assert len(sens["grid"][0]) == 3

    def test_meaningless_combination_left_blank(self):
        sens = compute_sensitivity(100.0, 10, {
            "discount_rates": [0.01],
            "terminal_growths": [0.015, 0.02],
        })
        assert sens["grid"][0] == [None, None]

    def test_valuation_exposes_sensitivity_when_valuable(self):
        res = compute_valuation(_capital_with_fcf(), price=10.0, shares=50.0)
        assert res["sensitivity"] is not None
        assert len(res["sensitivity"]["grid"]) == len(res["sensitivity"]["discount_rates"])
