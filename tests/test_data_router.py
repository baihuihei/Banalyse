"""数据路由测试：链解析、降级顺序、哨兵语义。

全程**不打网络**：把 ``_import_callable`` 与 ``vendors_providing`` 换成假的，
这样测的是路由逻辑本身，而不是"今天 EDGAR 通不通"。
"""
from pathlib import Path

import pytest

from banalyse.dataflows import router as router_module
from banalyse.dataflows.contract import DATA_METHODS
from banalyse.dataflows.errors import (
    NoDataError,
    VendorError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from banalyse.dataflows.registry import (
    VENDOR_REGISTRY,
    validate_methods_exist,
    vendor_market,
    vendors_providing,
)
from banalyse.dataflows.router import route_to_vendor
from banalyse.runtime_config import run_config


def _ok(payload):
    """返回一个总是成功的假供应商实现。"""
    def call(*args, **kwargs):
        return payload
    return call


def _raises(exc):
    def call(*args, **kwargs):
        raise exc
    return call


def _setup(monkeypatch, chain: list[str], implementations: dict):
    """把链固定成 ``chain``，并按名字分发假实现（未给实现的一律当"未安装"）。"""
    monkeypatch.setattr(router_module, "vendors_providing", lambda method: list(chain))

    def fake_import(vendor: str, method: str):
        impl = implementations.get(vendor)
        if impl is None:
            raise ImportError(f"no implementation for {vendor}.{method}")
        return impl

    monkeypatch.setattr(router_module, "_import_callable", fake_import)


def _route(method, chain, implementations, *args):
    # 两个市场都配成同一条链：这里测的是**路由/降级逻辑**，不想让
    # "代码形态→市场"的推断影响断言。市场推断本身在 test_market_inference.py 单独测。
    with run_config({"data_vendors": {"global": list(chain), "china": list(chain)}}):
        return route_to_vendor(method, *args)


class TestChainResolution:
    def test_chain_keeps_configured_order(self, monkeypatch):
        _setup(monkeypatch, ["yahoo", "sec_edgar"], {})
        with run_config({"data_vendors": {"global": ["sec_edgar", "yahoo"]}}):
            from banalyse.dataflows.router import vendor_chain
            assert vendor_chain("get_financials") == ["sec_edgar", "yahoo"]

    def test_vendors_not_configured_are_dropped(self, monkeypatch):
        _setup(monkeypatch, ["yahoo"], {})
        with run_config({"data_vendors": {"global": ["yahoo", "不存在的供应商"]}}):
            from banalyse.dataflows.router import vendor_chain
            assert vendor_chain("get_financials") == ["yahoo"]

    def test_empty_config_falls_back_to_all_available(self, monkeypatch):
        _setup(monkeypatch, ["yahoo", "akshare"], {})
        with run_config({"data_vendors": {"global": []}}):
            from banalyse.dataflows.router import vendor_chain
            assert vendor_chain("get_financials") == ["yahoo", "akshare"]


class TestFallbackOrder:
    def test_first_success_wins(self, monkeypatch):
        implementations = {"a": _ok({"from": "a"}), "b": _ok({"from": "b"})}
        _setup(monkeypatch, ["a", "b"], implementations)
        assert _route("get_financials", ["a", "b"], implementations, "X") == {"from": "a"}

    def test_no_data_in_one_vendor_tries_the_next(self, monkeypatch):
        """关键行为：一家说"没有"不等于别家也没有，必须继续往下试。"""
        implementations = {
            "yahoo": _raises(NoDataError("X", "yahoo 覆盖不到这只票")),
            "akshare": _ok({"from": "akshare"}),
        }
        _setup(monkeypatch, ["yahoo", "akshare"], implementations)
        assert _route("get_financials", ["yahoo", "akshare"], implementations, "X") == {
            "from": "akshare"
        }

    @pytest.mark.parametrize("error", [
        ImportError("没装这个库"),
        VendorNotConfiguredError("缺环境变量 FOO_API_KEY"),
        VendorRateLimitError("被限流"),
        VendorError("接口改版了"),
    ])
    def test_every_failure_kind_falls_through(self, monkeypatch, error):
        implementations = {"broken": _raises(error), "good": _ok("ok")}
        _setup(monkeypatch, ["broken", "good"], implementations)
        assert _route("get_financials", ["broken", "good"], implementations, "X") == "ok"

    def test_import_error_alone_is_survivable(self, monkeypatch):
        """全部供应商都没装 → 返回哨兵，不抛异常。"""
        _setup(monkeypatch, ["ghost"], {})
        out = _route("get_financials", ["ghost"], {}, "600519")
        assert isinstance(out, str) and out.startswith("NO_DATA_AVAILABLE")


class TestReturnTypes:
    def test_dict_payload_passes_through_unstringified(self, monkeypatch):
        """get_financials / get_quote 必须原样透传 dict，否则 compute_* 拿不到数据。"""
        payload = {"revenue": [1, 2], "net_income": [3, 4]}
        implementations = {"yahoo": _ok(payload)}
        _setup(monkeypatch, ["yahoo"], implementations)
        out = _route("get_financials", ["yahoo"], implementations, "AAPL")
        assert out == payload and isinstance(out, dict)

    def test_string_payload_passes_through(self, monkeypatch):
        implementations = {"sec_edgar": _ok("10-K 正文……")}
        _setup(monkeypatch, ["sec_edgar"], implementations)
        out = _route("get_filing", ["sec_edgar"], implementations, "AAPL", "10-K")
        assert out.startswith("10-K 正文")


class TestSentinelSemantics:
    def test_optional_category_degrades(self, monkeypatch):
        _setup(monkeypatch, ["ghost"], {})
        out = _route("get_company_profile", ["ghost"], {}, "AAPL")
        assert out.startswith("DATA_UNAVAILABLE")
        assert "fabricate" in out

    def test_core_category_is_explicit(self, monkeypatch):
        _setup(monkeypatch, ["ghost"], {})
        out = _route("get_financials", ["ghost"], {}, "AAPL")
        assert out.startswith("NO_DATA_AVAILABLE")
        assert "fabricate" in out

    def test_sentinel_carries_last_failure_reason(self, monkeypatch):
        """哨兵要能区分"没装库/没配 key/被限流/真没数据"，否则排查只能靠猜。"""
        implementations = {"yahoo": _raises(VendorRateLimitError("被限流了"))}
        _setup(monkeypatch, ["yahoo"], implementations)
        out = _route("get_company_profile", ["yahoo"], implementations, "AAPL")
        assert "yahoo" in out and "限流" in out

    def test_never_raises(self, monkeypatch):
        _setup(monkeypatch, ["a", "b"], {"a": _raises(RuntimeError("爆炸")),
                                        "b": _raises(ValueError("也爆炸"))})
        out = _route("get_company_profile", ["a", "b"],
                     {"a": _raises(RuntimeError("爆炸")), "b": _raises(ValueError("也爆炸"))},
                     "AAPL")
        assert isinstance(out, str)


class TestRegistryHealth:
    def test_no_contract_drift(self):
        # 声明的方法都应在契约里定义（早发现拼写/漂移）
        assert validate_methods_exist() == []

    def test_every_declared_vendor_method_is_actually_implemented(self):
        """回归测试：registry 里声明了却没写文件的供应商，运行到才 ImportError。

        这正是"四个供应商全部 not importable"的根因，必须让 CI 挡住。
        """
        root = Path(router_module.__file__).resolve().parent / "vendors"
        missing = [
            str(root / vendor_market(vendor) / vendor / f"{method}.py")
            for vendor, spec in VENDOR_REGISTRY.items()
            for method in spec.get("provides", [])
            if not (root / vendor_market(vendor) / vendor / f"{method}.py").exists()
        ]
        assert missing == [], f"已声明但未实现的供应商方法：{missing}"

    def test_without_ua_sec_edgar_is_excluded(self, monkeypatch):
        """SEC 强制要 UA 头；没配时它不该出现在候选里（否则运行时白试一轮）。"""
        monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
        assert "sec_edgar" not in vendors_providing("get_filing")
        assert "sec_edgar" not in vendors_providing("get_financials")

    def test_with_ua_sec_edgar_is_in_every_declared_slot(self, monkeypatch):
        monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Test test@example.com")
        for method in ("get_filing", "get_financials", "get_company_profile",
                       "get_quote", "get_news"):
            assert "sec_edgar" in vendors_providing(method)

    def test_missing_ua_is_reported_as_an_actionable_hint(self, monkeypatch):
        """链为空时不能只说"没有供应商"，要点名缺哪个环境变量。"""
        monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
        with run_config({"data_vendors": {"global": ["sec_edgar"]}}):
            out = route_to_vendor("get_financials", "AAPL")
        assert "SEC_EDGAR_USER_AGENT" in out

    def test_macro_slot_is_served_by_both_market_chains(self, monkeypatch):
        """回归：折现基准要按市场选国债，所以两条链都得能提供宏观槽位。"""
        monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Test test@example.com")
        assert "sec_edgar" in vendors_providing("get_macro_indicators")
        assert "akshare" in vendors_providing("get_macro_indicators")

    def test_slots_with_no_provider_are_reported_as_such(self, monkeypatch):
        """可比公司这类槽位两家都没实现，要说清楚是"没实现"而不是"没配"。"""
        monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Test test@example.com")
        with run_config({"data_vendors": {"global": ["sec_edgar"]}}):
            out = route_to_vendor("get_peer_metrics", "AAPL")
        assert "没有任何已注册的供应商实现" in out

    def test_offline_capability_map(self, monkeypatch):
        """把两家合起来能覆盖的范围钉住：剩下的空洞必须持续显式暴露。"""
        monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Test test@example.com")
        unserved = sorted(m for m in DATA_METHODS if not vendors_providing(m))
        assert unserved == ["get_peer_metrics"]

    def test_price_slots_have_a_provider_only_because_of_akshare(self, monkeypatch):
        """回归：SEC 结构上没有行情。行情槽位的唯一希望是 AKShare，不能被误删。"""
        monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Test test@example.com")
        providers = vendors_providing("get_price_history")
        assert "sec_edgar" not in providers
        assert providers == ["akshare"]
