"""sec_edgar 供应商：EDGAR 原文（10-K 年报 / DEF 14A 股东委托书）。

这是「商业模式」与「管理层作为」两个维度**唯一**的原始材料来源 ——
《方向.txt》特别强调 DEF 14A 比 10-K 更重要（高管薪酬结构、股权激励、
资本配置行为都在里面），而这两份文件只有 EDGAR 有。

配置（必需，SEC 强制要求带可联系的身份，否则 403）：
    SEC_EDGAR_USER_AGENT=Your Name your@email.com

限额 10 req/s，所以 ticker→CIK 映射表必须缓存，不重复拉。
注意：EDGAR 只覆盖美股（申报主体是美股发行人）；A 股年报得另接巨潮等源。
"""
import time

from ....errors import NoDataError
from ..._shared import require_dependency, require_env, to_float

VENDOR = "sec_edgar"
UA_ENV = "SEC_EDGAR_USER_AGENT"

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_CACHE_TTL_SECONDS = 86400
_tickers_cache: dict = {"data": None, "at": 0.0}

# companyfacts 单份可达十几 MB，一轮分析里三个槽位都要用它 —— 必须缓存
_facts_cache: dict[str, dict] = {}


def session():
    """带 UA 的 HTTP 会话；缺 requests 抛 ImportError 由 router 跳过本供应商。"""
    requests = require_dependency("requests", VENDOR)
    http = requests.Session()
    http.headers.update({
        "User-Agent": require_env(UA_ENV, VENDOR),
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    })
    return http


def ticker_map(http) -> dict:
    """ticker → CIK 全量映射（约 1MB），缓存 24 小时。"""
    now = time.time()
    if _tickers_cache["data"] is None or now - _tickers_cache["at"] > _CACHE_TTL_SECONDS:
        resp = http.get(_TICKERS_URL, timeout=20)
        resp.raise_for_status()
        _tickers_cache["data"] = resp.json()
        _tickers_cache["at"] = now
    return _tickers_cache["data"]


def cik_for(http, symbol: str) -> str:
    """ticker → 10 位补零 CIK；找不到说明不是美股。"""
    wanted = symbol.upper().split(".")[0]
    for row in ticker_map(http).values():
        if str(row.get("ticker", "")).upper() == wanted:
            return str(row["cik_str"]).zfill(10)
    raise NoDataError(symbol, f"{VENDOR}: EDGAR 中找不到该 ticker 的 CIK（仅支持美股）")


def submissions(http, cik: str) -> dict:
    resp = http.get(_SUBMISSIONS_URL.format(cik=cik), timeout=30)
    resp.raise_for_status()
    return resp.json()


def company_facts(http, cik: str) -> dict:
    """XBRL companyfacts（含 ``us-gaap`` 与 ``dei`` 两个命名空间），按 CIK 缓存。

    单份可达十几 MB，而 ``get_financials`` / ``get_quote`` 都要读它，
    不缓存的话一轮分析要重复下载多次。
    """
    if cik not in _facts_cache:
        resp = http.get(FACTS_URL.format(cik=cik), timeout=60)
        resp.raise_for_status()
        _facts_cache[cik] = resp.json()
    return _facts_cache[cik]


def latest_dei(facts: dict, tag: str, units: tuple[str, ...] = ("shares", "USD")):
    """取某个 DEI 标签的最新一条申报值。

    DEI（封面页事实）没有年度序列的概念，每条对应一次申报，所以按
    ``end``（报告期未）取最新 —— 股本就是要用离现在最近的那个数。
    返回 ``(值, 期末日, 表单, 申报日)``，取不到返回 ``(None, None, None, None)``。
    """
    block = ((facts.get("facts") or {}).get("dei") or {}).get(tag) or {}
    candidates = []
    for unit in units:
        candidates.extend((block.get("units") or {}).get(unit) or [])
    if not candidates:
        return None, None, None, None

    newest = max(candidates, key=lambda entry: (str(entry.get("end") or ""),
                                                str(entry.get("filed") or "")))
    return (
        to_float(newest.get("val")),
        str(newest.get("end") or ""),
        newest.get("form"),
        str(newest.get("filed") or ""),
    )


def recent_filings(recent: dict) -> list[dict]:
    """把 ``submissions.recent`` 的并行列表转成一行一条的 dict 列表。"""
    fields = ("form", "filingDate", "reportDate", "accessionNumber",
              "primaryDocument", "primaryDocDescription", "items")
    columns = {name: recent.get(name) or [] for name in fields}
    length = min((len(values) for values in columns.values()), default=0)
    return [
        {name: values[index] for name, values in columns.items()}
        for index in range(length)
    ]


def pick_filing(recent: dict, form_type: str) -> tuple[str, str, str] | None:
    """挑最新一份目标表单：先精确匹配，再允许 ``10-K/A`` 这类修订版。

    返回 (accessionNumber, primaryDocument, filingDate)；找不到返回 None。
    注意必须带上 ``form`` 一起放进候选，否则会拿 accession 去比表类型。
    """
    rows = [
        {"form": form, "accession": accession, "document": document, "filed": filed}
        # strict=False：EDGAR 的几个并行列表理应等长，真不等长时宁可按最短的取，
        # 也不要因为一条脏数据把整份年报查询打挂
        for form, accession, document, filed in zip(
            recent.get("form") or [],
            recent.get("accessionNumber") or [],
            recent.get("primaryDocument") or [],
            recent.get("filingDate") or [],
            strict=False,
        )
        if form and document
    ]

    target = form_type.upper()
    for row in rows:
        if row["form"].upper() == target:
            return row["accession"], row["document"], row["filed"]
    for row in rows:
        if row["form"].upper().startswith(target):
            return row["accession"], row["document"], row["filed"]
    return None


# ---------------------------------------------------------------- 对外入口
# 会话生命周期由本模块自己管，消费方（get_*）只调下面这几个函数。
# 好处：``session`` / ``submissions`` / ``company_facts`` 都是本模块的全局名，
# 测试可以整体替换，不会因为 `from . import session` 把函数按值绑定而换不掉
# （那样测试会真的去请求 EDGAR）。


def submissions_for(symbol: str) -> tuple[str, dict]:
    """取 ``(cik, submissions 全文)`` —— 主体信息、申报索引、8-K item 都在这份里。"""
    with session() as http:
        cik = cik_for(http, symbol)
        return cik, submissions(http, cik)


def facts_for(symbol: str) -> tuple[str, dict]:
    """取 ``(cik, companyfacts 全文)`` —— 含 ``us-gaap`` 与 ``dei`` 两个命名空间。"""
    with session() as http:
        cik = cik_for(http, symbol)
        return cik, company_facts(http, cik)


def raw_filing(symbol: str, form_type: str = "10-K") -> dict:
    """取一份原始申报正文（**未做 HTML 清洗**），交给 get_filing 去解析。"""
    with session() as http:
        cik = cik_for(http, symbol)
        recent = (submissions(http, cik).get("filings") or {}).get("recent") or {}
        picked = pick_filing(recent, form_type)
        if picked is None:
            raise NoDataError(symbol, f"{VENDOR}: 未找到 {form_type} 披露")

        accession, document, filed = picked
        url = filing_url(cik, accession, document)
        resp = http.get(url, timeout=60)
        resp.raise_for_status()
        return {
            "symbol": symbol,
            "form": form_type,
            "cik": cik,
            "accession": accession,
            "filed": filed,
            "source_url": url,
            "html": resp.text,
        }


def filing_url(cik: str, accession: str, document: str) -> str:
    return _ARCHIVE_URL.format(
        cik=int(cik), accession=accession.replace("-", ""), doc=document
    )
