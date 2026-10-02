"""探针：校验 ticker_problem 的判定。用完即删。"""
from pathlib import Path

from banalyse.dataflows.market import ticker_problem

CASES = ["600519", "600519.SS", "AAPL", "aapl", "贵州茅台", "sh600519", "00700", "0700.HK", ""]
lines = [f"{c!r:14s} -> {ticker_problem(c) or 'OK（放行）'}" for c in CASES]
Path("_probe_out.txt").write_text("\n".join(lines), encoding="utf-8")
print("written")
