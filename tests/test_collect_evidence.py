"""取数节点的硬约束：检索只认股票代码，不认公司名。

为什么值得单独立一条测试
------------------------
市场是按**代码形态**推断的（纯数字 → A 股走 AKShare，含字母 → 美股走 SEC），
所以"用哪个源、去查哪个主体"完全由代码决定。一旦公司名参与检索，会出现两类静默错误：

  · 名字会被当成美股代码，整条链走 SEC，A 股四个维度全部"材料未取到"；
  · 按名字搜可能命中**同名公司**，取回错主体的数据 —— 这比取不到更危险，
    因为报告会照常生成，没人看得出主体错了。

这两条都不会报错，所以只能靠测试把它钉住，防止将来被当成"顺手加的兜底"加进去。
"""
from banalyse.graph.nodes import collect_evidence


def _state(**over):
    state = {
        "ticker": "600519",
        "company_name": "贵州茅台",     # 故意给一个在别处真能匹配到东西的名字
        "report_date": "2026-09-29",
        "market": "china",
    }
    state.update(over)
    return state


def test_every_lookup_passes_the_ticker_and_nothing_else(monkeypatch):
    calls: list[tuple] = []

    def spy(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return {"ok": True}

    monkeypatch.setattr(collect_evidence, "route_to_vendor", spy)
    collect_evidence.make()(_state())

    assert calls, "应当至少发起一次取数"
    for method, args, kwargs in calls:
        assert args[0] == "600519", f"{method} 的第一个参数必须是股票代码"
        assert "贵州茅台" not in str(args), f"{method} 把公司名带进了检索参数"
        assert "贵州茅台" not in str(kwargs), f"{method} 把公司名带进了检索关键字"


def test_company_name_survives_only_as_archival_metadata(monkeypatch):
    """公司名只进 _meta（落档 + 给模型当上下文），不参与取数。"""
    monkeypatch.setattr(collect_evidence, "route_to_vendor", lambda *a, **k: {"ok": True})
    out = collect_evidence.make()(_state())

    meta = out["evidence"]["_meta"]
    assert meta["ticker"] == "600519"
    assert meta["company"] == "贵州茅台"


def test_missing_company_name_still_analyses_by_code(monkeypatch):
    """不填公司名不能影响任何一次取数 —— 代码本身就是完整的检索键。"""
    with_name: list[tuple] = []
    without_name: list[tuple] = []

    def spy(bucket):
        def record(method, *args, **kwargs):
            bucket.append((method, args))
            return {"ok": True}
        return record

    monkeypatch.setattr(collect_evidence, "route_to_vendor", spy(with_name))
    collect_evidence.make()(_state())

    monkeypatch.setattr(collect_evidence, "route_to_vendor", spy(without_name))
    collect_evidence.make()(_state(company_name=""))

    assert with_name == without_name
