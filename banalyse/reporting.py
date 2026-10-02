"""分析结果落盘：一次分析 = 一个自包含的 JSON 文件。"""
import json
import os

from .dataflows.symbols import safe_ticker_component
from .paths import DEFAULT_RESULTS_DIR, resolve


def write_report(results_dir: str, ticker: str, report_date: str, state: dict) -> str:
    """把 final_report 落盘为 JSON，返回文件路径。

    ``results_dir`` 允许写相对路径（相对项目根，见 ``paths.resolve``）——
    配置里不必出现盘符，整目录搬到哪台机器都能落到同一处；
    留空则回落到项目默认的 ``record/``。
    """
    root = resolve(results_dir or DEFAULT_RESULTS_DIR)
    directory = os.path.join(root, safe_ticker_component(ticker))
    os.makedirs(directory, exist_ok=True)
    safe_date = str(report_date).replace(":", "-").replace("/", "-")
    path = os.path.join(directory, f"report_{safe_date}.json")

    final = state.get("final_report") or {}
    payload = {
        "company": final.get("company", {}),
        # 四维度报告
        "reports": final.get("reports", {}),
        # 汇总
        "conclusion": final.get("conclusion", ""),
        "analysis_document": final.get("analysis_document", ""),
        "disclaimer": final.get("disclaimer", ""),
        "guardrail": final.get("guardrail", {}),
        # 确定性计算结果
        "capital": final.get("capital", {}),
        "valuation": final.get("valuation", {}),
        # 完整文档 + 执行轨迹
        "markdown": final.get("markdown", ""),
        "trace": state.get("trace", []),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path
