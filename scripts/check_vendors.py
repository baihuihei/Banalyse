"""逐个供应商打真实调用，把原始返回 dump 出来 —— 用来校对字段名。

为什么需要它
------------
数据供应商的接口名与字段口径会跨版本变动，而"字段对不上"的表现
往往不是报错，而是静默变成"无数据"。所以落地新供应商、或升级依赖之后，
先跑这个脚本看真实返回，比读代码猜字段名可靠得多。

用法：
    python scripts/check_vendors.py AAPL                # 含字母 → 海外链（SEC EDGAR）
    python scripts/check_vendors.py 600519              # 纯数字 → A 股链（AKShare）
    python scripts/check_vendors.py 600519 --only get_financials

市场由代码形态推断（见 ``dataflows/market.py``），所以**没有 --market 选项** ——
少一个能跟代码不一致的入参，就少一类"选了 A 股链却传美股代码"的错配。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from banalyse.dataflows.market import infer_market, market_label  # noqa: E402
from banalyse.dataflows.router import route_to_vendor, vendor_chain  # noqa: E402

# (方法, 附加参数) —— 覆盖 dimensions.py 声明的全部槽位
SLOTS = (
    ("get_company_profile", ()),
    ("get_quote", ()),
    ("get_financials", ()),
    ("get_price_history", ("2021-01-01", "2024-12-31")),
    ("get_news", ()),
    ("get_filing", ("10-K",)),
    ("get_filing", ("DEF 14A",)),
    ("get_macro_indicators", ()),
    ("get_peer_metrics", ()),
)

# 输出截断长度：够看清结构，又不至于刷屏
PREVIEW = 900


def _preview(payload) -> str:
    if isinstance(payload, str):
        return payload[:PREVIEW]
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:PREVIEW]


def main() -> int:
    parser = argparse.ArgumentParser(description="校验数据供应商链的真实返回")
    parser.add_argument("ticker", help="标的代码，如 AAPL / 600519 / 600519.SS")
    parser.add_argument("--only", help="只测某一个方法")
    args = parser.parse_args()

    market = infer_market(args.ticker)
    print(f"标的 {args.ticker} → 市场 {market}（{market_label(market)}）")

    failures = 0
    for method, extra in SLOTS:
        if args.only and method != args.only:
            continue
        chain = vendor_chain(method, args.ticker)
        label = f"{method}{extra if extra else ''}"
        print(f"\n=== {label} ===")
        print(f"供应商链: {chain or '（空 —— 检查 data_vendors 配置 / key）'}")

        payload = route_to_vendor(method, args.ticker, *extra)
        text = str(payload)
        sentinel = text.startswith(("NO_DATA_AVAILABLE", "DATA_UNAVAILABLE"))
        if sentinel:
            failures += 1
            print(f"[哨兵] {text[:400]}")
        else:
            print(_preview(payload))

    print(f"\n--- 完成：{failures} 个槽位未取到数据 ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
