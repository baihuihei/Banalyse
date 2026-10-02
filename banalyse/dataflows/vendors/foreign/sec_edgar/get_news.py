"""近期重大事件 —— 用 8-K 申报替代"新闻"。

为什么这是更好的选择
--------------------
第三方新闻源是二手加工、还常常抓不到。而 8-K 是公司**自己按法定要求**
向 SEC 报备的重大事件，带标准化的 **item 代码**，信息密度远高于新闻标题，
而且信号性质精确对应分析维度：

    4.02 前期财报不可依赖（财务重述）→ 管理层诚信
    2.06 重大减值 / 2.01 完成收购     → 资本配置行为
    5.02 董监高变动 / 4.01 更换审计师 → 管理层稳定性
    2.02 业绩发布                     → 经营节奏

数据全部来自 ``submissions.recent``，**不需要额外下载任何文件**。
"""
from ..._shared import ensure
from . import VENDOR, filing_url, recent_filings, submissions_for

LIMIT = 15

# 8-K 标准 item 代码 → 中文含义（只列与分析维度相关的；其余留原码）
ITEM_LABELS = {
    "1.01": "签订重大协议",
    "1.02": "终止重大协议",
    "1.03": "破产或接管",
    "2.01": "完成收购或资产处置",
    "2.02": "业绩发布（经营成果与财务状况）",
    "2.03": "新增直接财务义务",
    "2.04": "触发加速或增加偿债义务的事件",
    "2.05": "退出或处置活动相关费用",
    "2.06": "重大减值",
    "3.01": "退市通知或不符合持续上市标准",
    "3.02": "未注册的股权证券发行",
    "3.03": "证券持有人权利重大变更",
    "4.01": "更换审计师",
    "4.02": "前期财报不再可依赖（财务重述信号）",
    "5.01": "控制权变更",
    "5.02": "董监高变动",
    "5.03": "章程或细则修订",
    "5.07": "股东表决结果",
    "7.01": "公平披露（Regulation FD）",
    "8.01": "其他重大事件",
    "9.01": "财务报表与附件",
}

# 这几种直接关系"管理层作为"与"资本配置"，单列出来给分析层提个醒
MATERIAL_ITEMS = {"2.01", "2.06", "4.01", "4.02", "5.01", "5.02"}


def decode_items(raw) -> list[dict]:
    """把 ``"2.02,9.01"`` 这种 item 串解成带含义的列表。"""
    items = []
    for code in str(raw or "").split(","):
        code = code.strip()
        if code:
            items.append({"code": code, "label": ITEM_LABELS.get(code, "未收录的 item 代码")})
    return items


def call(symbol: str) -> dict:
    cik, payload = submissions_for(symbol)
    recent = (payload.get("filings") or {}).get("recent") or {}

    events = []
    for row in recent_filings(recent):
        form = str(row.get("form") or "")
        if not form.startswith("8-K"):
            continue
        items = decode_items(row.get("items"))
        events.append({
            "date": row.get("filingDate"),
            "form": form,
            "items": items,
            "material": bool({item["code"] for item in items} & MATERIAL_ITEMS),
            "url": filing_url(cik, row["accessionNumber"], row["primaryDocument"]),
        })
        if len(events) >= LIMIT:
            break

    if not events:
        return ensure(None, symbol, VENDOR, "EDGAR 近期无 8-K 申报")

    return {
        "symbol": symbol,
        "cik": cik,
        "source": VENDOR,
        "events": events,
        "material_count": sum(1 for event in events if event["material"]),
        "note": "8-K 是公司法定报备的重大事件，不是新闻；按申报日倒序",
    }
