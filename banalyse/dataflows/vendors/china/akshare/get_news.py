"""A 股个股新闻（东财）。

与 SEC 那侧 ``get_news`` 的分工值得说清楚：
  · SEC 的 8-K 是**法定**重大事件披露，权威但对 A 股不可用；
  · 东财新闻是**媒体**聚合，时效好、覆盖广，但属于二手信息。

所以本模块的输出在报告里必须标成"媒体来源"，不能与法定披露混为一谈。
返回最近若干条，正文截断 —— 新闻全文对四维度分析的边际价值很低，
而它会迅速撑爆 evidence。
"""
from ....errors import NoDataError
from . import VENDOR, code_of, is_frame, require_akshare

# 返回条数与正文截断长度：标题+摘要足够，全文留给链接
MAX_ITEMS = 30
SUMMARY_CHARS = 160


def _text(row, name: str):
    if name not in row.index:
        return None
    raw = row.get(name)
    text = str(raw).strip() if raw is not None else ""
    return text or None


def call(symbol: str) -> dict:
    ak = require_akshare()
    code = code_of(symbol)

    frame = ak.stock_news_em(symbol=code)
    if not is_frame(frame):
        raise NoDataError(symbol, "东财个股新闻接口未返回数据（可能被限流或该股无新闻）")

    items = []
    for index in range(min(len(frame), MAX_ITEMS)):
        row = frame.iloc[index]
        title = _text(row, "新闻标题")
        if not title:
            continue
        content = _text(row, "新闻内容") or ""
        items.append({
            "date": _text(row, "发布时间"),
            "title": title,
            "source": _text(row, "文章来源"),
            "url": _text(row, "新闻链接"),
            "summary": content[:SUMMARY_CHARS] or None,
        })

    if not items:
        raise NoDataError(symbol, "东财个股新闻标题整列为空")

    return {
        "symbol": symbol,
        "code": code,
        "source": VENDOR,
        "count": len(items),
        "items": items,
        "note": (
            "东财**媒体**新闻聚合（非法定披露）。只保留标题与摘要，"
            "正文请按 url 获取；引用时须标注为媒体来源。"
        ),
    }
