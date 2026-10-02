"""A 股公告（东财）：标题 + 摘要 + 原文链接。

**这不是 10-K 原文搬运。** SEC 那侧的 ``get_filing`` 会下载完整 HTML 并按
章节裁剪；AKShare 只能给"公告标题 / 类型 / 日期 / 链接"和一小段摘要。
所以本模块的定位是**索引**，不是原文：

  · 对「管理层作为」维度，公告标题列表本身就很有信息量
    （股权激励、关联交易、人事变动、监管问询都能一眼看出来）；
  · 需要正文时，报告里给出 URL，由人或后续工具去取，而不是在这里假装读到了。

表单类型映射
------------
调用方传的是 SEC 口径的表单名（``10-K`` / ``DEF 14A``），在 A 股语境下
映射到东财的公告分类（``财务报告`` / ``股东大会``）。映射不到的抛
``NoDataError`` —— 与其返回一堆无关公告，不如明确说"这类表单 A 股没有"。
"""
from datetime import date, timedelta

from ....errors import NoDataError
from . import VENDOR, code_of, is_frame, require_akshare, soft

# SEC 表单名 → 东财公告分类
_FORM_CATEGORY = {
    "10-K": "财务报告",
    "10-Q": "财务报告",
    "8-K": "重大事项",
    "DEF 14A": "股东大会",
}

# 公告回溯年数：够覆盖近几期定期报告与主要公司治理事件
LOOKBACK_YEARS = 3
MAX_ITEMS = 40


def _text(row, name: str):
    if name not in row.index:
        return None
    raw = row.get(name)
    text = str(raw).strip() if raw is not None else ""
    return text or None


def call(symbol: str, form_type: str = "10-K") -> dict:
    category = _FORM_CATEGORY.get(str(form_type).strip().upper())
    if not category:
        raise NoDataError(
            symbol,
            f"A 股没有 {form_type} 这类表单；可用的映射：{sorted(_FORM_CATEGORY)}",
        )

    ak = require_akshare()
    code = code_of(symbol)

    end = date.today()
    begin = end - timedelta(days=365 * LOOKBACK_YEARS)

    frame = soft(
        ak.stock_individual_notice_report,
        security=code,
        symbol=category,
        begin_date=begin.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if not is_frame(frame):
        raise NoDataError(symbol, f"东财近 {LOOKBACK_YEARS} 年没有「{category}」类公告")

    items = []
    for index in range(min(len(frame), MAX_ITEMS)):
        row = frame.iloc[index]
        title = _text(row, "公告标题")
        if not title:
            continue
        items.append({
            "date": _text(row, "公告日期"),
            "type": _text(row, "公告类型"),
            "title": title,
            "url": _text(row, "网址"),
        })

    if not items:
        raise NoDataError(symbol, f"「{category}」类公告标题整列为空")

    return {
        "symbol": symbol,
        "code": code,
        "source": VENDOR,
        "form": form_type,
        "category": category,
        "count": len(items),
        "items": items,
        "note": (
            f"东财「{category}」类公告索引（近 {LOOKBACK_YEARS} 年，最多 {MAX_ITEMS} 条）："
            "只含标题与链接，**不含正文**；需要正文请按 url 自行获取。"
        ),
    }
