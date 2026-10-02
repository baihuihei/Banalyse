"""FastAPI 应用：网页端配置 + 连通性测试 + 报告生成。

默认仅绑 ``127.0.0.1``（见 ``__main__``），可设 ``BA_WEB_TOKEN`` 加一层口令保护。

路由
----
- ``GET    /api/providers``          可选 provider 清单（驱动 UI 联动）
- ``GET    /api/config``             当前配置（key 已掩码）
- ``PUT    /api/config``             保存配置（空 key = 保留原值）
- ``DELETE /api/config/key``         显式清除已存 key
- ``POST   /api/config/reset``       重置全部网页配置
- ``POST   /api/config/test``        用当前/临时配置试连通
- ``POST   /api/reports``            跑图生成报告（每次生成都会自动落盘到 results_dir）
- ``GET    /api/reports/{t}/{d}``    读取已落盘报告
- ``GET    /api/history``            已落盘报告清单（代码 / 名称 / 时间），新→旧
- ``DELETE /api/history/{t}/{d}``    删除某一份已落盘报告
- ``GET    /api/health``             健康检查
"""
import contextlib
import json
import os
import time
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agents.dimensions import DIMENSION_ORDER
from ..dataflows.market import ticker_problem
from ..dataflows.symbols import safe_ticker_component
from ..graph.workflow import BanalyseGraph
from ..llm_clients.factory import build_llm_kwargs, create_llm_client
from ..llm_clients.providers import PROVIDER_REGISTRY
from ..paths import DEFAULT_RESULTS_DIR, resolve
from ..runtime_config import get_config as _default_config
from .config_store import ConfigStore, list_providers, provider_defaults

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# ---------------------------------------------------------------- 落盘路径
def _safe_report_name(report_date: str) -> str:
    """文件名里的日期（与 ``reporting.write_report`` 用同一套替换）。"""
    return str(report_date).replace(":", "-").replace("/", "-")


def _read_company_meta(path: str) -> dict:
    """只取已落盘报告的 ``company`` 段做列表展示。

    读不动就返回空 dict —— 一份文件坏掉不该让整个历史列表打不开。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    company = data.get("company") if isinstance(data, dict) else None
    return company if isinstance(company, dict) else {}


# ---------------------------------------------------------------- 请求模型
class ConfigPatch(BaseModel):
    """部分更新：只传想改的字段；未传字段不动。"""

    llm_provider: str | None = None
    api_key: str | None = None
    backend_url: str | None = None
    deep_think_llm: str | None = None
    quick_think_llm: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    output_language: str | None = None
    results_dir: str | None = None


class TestRequest(BaseModel):
    """连通性测试：可临时覆盖保存的配置（便于「先测再存」）。"""

    llm_provider: str | None = None
    api_key: str | None = None
    backend_url: str | None = None
    deep_think_llm: str | None = None
    quick_think_llm: str | None = None
    prompt: str = "请只回复两个字：正常"


class GenerateRequest(BaseModel):
    """生成请求：股票代码 + 可选公司名 + 可选维度子集。

    市场由 ``ticker`` 形态推断（纯数字=A 股，含字母=海外），不再由前端提供；
    ``company`` 只用于展示，留空时图内部回落到 ticker。
    """

    ticker: str = Field(..., min_length=1)
    company: str = ""
    report_date: str = ""
    # 只跑指定维度；不传则用配置里的全部四维度（清单驱动，见 agents/dimensions.py）
    dimensions: list[str] | None = None


# ---------------------------------------------------------------- 辅助函数
def _merge_overrides(base: dict, patch: dict) -> dict:
    """把 patch 中非空字段盖到 base 上。"""
    out = dict(base)
    for key, value in (patch or {}).items():
        if value is not None and value != "":
            out[key] = value
    return out


def _effective_config(store: ConfigStore, patch: dict) -> dict:
    """保存配置 ← 临时 patch（测试连通时用，不写盘）。"""
    base = store.to_run_config()
    over = _merge_overrides({}, patch)

    provider = (over.get("llm_provider") or base.get("llm_provider") or "mock").lower()
    if provider not in PROVIDER_REGISTRY:
        raise HTTPException(status_code=400, detail=f"未知 provider: {provider}")
    spec = PROVIDER_REGISTRY[provider]
    defaults = provider_defaults(provider)

    cfg = {
        "llm_provider": provider,
        "deep_think_llm": over.get("deep_think_llm")
        or base.get("deep_think_llm")
        or defaults["default_deep_model"],
        "quick_think_llm": over.get("quick_think_llm")
        or base.get("quick_think_llm")
        or defaults["default_quick_model"],
        "backend_url": over.get("backend_url") or base.get("backend_url") or spec.get("base_url"),
        "temperature": base.get("temperature", 0.0),
        "max_tokens": base.get("max_tokens", 8192),
    }
    # key 优先级：临时传入 > 网页已存 > 环境变量
    key = over.get("api_key") or base.get("api_key")
    env_name = spec.get("env")
    if not key and env_name:
        key = os.getenv(env_name)
    if key:
        cfg["api_key"] = key
    return cfg



# ---------------------------------------------------------------- 应用工厂
def create_app(store: ConfigStore | None = None, require_token: bool | None = None) -> FastAPI:
    """构建 FastAPI 应用。``store`` 可注入以便测试隔离。"""
    store = store or ConfigStore()
    app = FastAPI(title="Banalyse", version="0.1.0")

    token = os.getenv("BA_WEB_TOKEN")
    guard = bool(token) if require_token is None else require_token

    def auth(x_web_token: str | None = Header(default=None, alias="X-Web-Token")):
        """设了 BA_WEB_TOKEN 才校验；本地开发默认关闭。"""
        if guard and x_web_token != token:
            raise HTTPException(status_code=401, detail="无效的 X-Web-Token")

    # ------------------------------------------------ 落盘目录与路径
    def results_dir() -> str:
        """报告落盘根目录 = 图真正写入的那个目录（绝对路径）。

        网页配置优先，没配时用项目默认（``record``，相对项目根解析，
        见 ``paths.resolve``）。配置里可以写相对目录（如 ``record/out``），
        它相对**项目根**而非当前工作目录解析，换机器/换启动目录都落到同一处。

        必须与 ``reporting.write_report`` 取同一个值：生成写这里、读取找那里，
        界面就会一片空白且查不出原因（此前 ``results_dir`` 未配置时这里会取到
        ``None`` 直接 500）。

        这里必须调 ``_default_config``（runtime_config 那个），不能调本函数
        下面那个同名路由 ``get_config()``：那个 handler 没有任何参数，
        被调用时返回的是给前端的配置字典，里面 ``results_dir`` 恒为 ""，
        于是历史列表扫的是空路径 → 一条记录也没有，界面上永远是空列表。
        """
        configured = (
            store.to_run_config().get("results_dir")
            or _default_config()["results_dir"]
            or DEFAULT_RESULTS_DIR
        )
        return resolve(configured)

    def saved_report_path(ticker: str, report_date: str) -> str:
        """某份已落盘报告的路径；目录与文件名都用与写入端相同的清洗规则。"""
        for label, value in (("ticker", ticker), ("report_date", report_date)):
            if ".." in value or "/" in value or "\\" in value:
                raise HTTPException(status_code=400, detail=f"非法 {label}")
        directory = os.path.join(results_dir(), safe_ticker_component(ticker))
        return os.path.join(directory, f"report_{_safe_report_name(report_date)}.json")

    # ------------------------------------------------ provider 清单
    @app.get("/api/providers", dependencies=[Depends(auth)])
    def get_providers():
        return {"providers": list_providers()}

    # ------------------------------------------------ 配置读写
    @app.get("/api/config", dependencies=[Depends(auth)])
    def get_config():
        return store.masked()

    @app.put("/api/config", dependencies=[Depends(auth)])
    def put_config(patch: ConfigPatch):
        incoming = patch.model_dump(exclude_none=True)
        provider = incoming.get("llm_provider")
        if provider and provider.lower() not in PROVIDER_REGISTRY:
            raise HTTPException(status_code=400, detail=f"未知 provider: {provider}")
        if provider:
            incoming["llm_provider"] = provider.lower()
        store.save(incoming)
        return store.masked()

    @app.delete("/api/config/key", dependencies=[Depends(auth)])
    def delete_key():
        store.clear_key()
        return store.masked()

    @app.post("/api/config/reset", dependencies=[Depends(auth)])
    def reset_config():
        store.reset()
        return store.masked()

    # ------------------------------------------------ 连通性测试
    @app.post("/api/config/test", dependencies=[Depends(auth)])
    def test_connection(req: TestRequest):
        payload = req.model_dump(exclude_none=True)
        prompt = payload.pop("prompt", None) or "请只回复两个字：正常"
        cfg = _effective_config(store, payload)
        started = time.perf_counter()
        try:
            client = create_llm_client(
                cfg["llm_provider"],
                cfg["quick_think_llm"],
                cfg.get("backend_url"),
                **build_llm_kwargs(cfg),
            )
            reply = client.get_llm().invoke(prompt)
        except Exception as exc:  # noqa: BLE001 —— 外部 SDK 异常类型不可枚举，原样回给前端
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "provider": cfg["llm_provider"],
                    "model": cfg["quick_think_llm"],
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        text = getattr(reply, "content", str(reply))
        return {
            "ok": True,
            "provider": cfg["llm_provider"],
            "model": cfg["quick_think_llm"],
            "latency_ms": elapsed_ms,
            "reply": text[:500],
        }

    # ------------------------------------------------ 报告生成
    @app.post("/api/reports", dependencies=[Depends(auth)])
    def create_report(req: GenerateRequest):
        # 代码填法决定走哪条数据链，填错会静默跑出一份"什么都没取到"的报告，
        # 所以在入口就把话说清楚，而不是让用户自己去猜。
        problem = ticker_problem(req.ticker)
        if problem:
            raise HTTPException(status_code=400, detail=problem)

        cfg = store.to_run_config()
        requested = list(cfg.get("dimensions") or DIMENSION_ORDER)
        if req.dimensions:
            unknown = [k for k in req.dimensions if k not in DIMENSION_ORDER]
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail=f"未知分析维度 {unknown}；可选：{list(DIMENSION_ORDER)}",
                )
            cfg["dimensions"] = list(req.dimensions)
            requested = list(req.dimensions)
        try:
            graph = BanalyseGraph(config=cfg)
            # company 留空时图内部会用 ticker 当展示名
            state = graph.analyze(
                req.ticker,
                company=req.company.strip(),
                report_date=req.report_date or None,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

        report = state.get("final_report") or {}
        return {
            "ticker": state.get("ticker"),
            "company_name": state.get("company_name"),
            "report_date": state.get("report_date"),
            "market": state.get("market"),
            "provider": cfg.get("llm_provider"),
            # 实际用的快速模型：出问题时"选了 X 却跑出 Y"能一眼对上
            "model": cfg.get("quick_think_llm"),
            # 本次请求要求跑的维度（顺序同 DIMENSION_ORDER）
            "requested_dimensions": [k for k in DIMENSION_ORDER if k in requested],
            # 四维度子报告
            "reports": report.get("reports", {}),
            # 汇总交付物
            "conclusion": report.get("conclusion", ""),
            "analysis_document": report.get("analysis_document", ""),
            "markdown": report.get("markdown", ""),
            "disclaimer": report.get("disclaimer", ""),
            "guardrail": report.get("guardrail", {}),
            # 确定性计算结果
            "capital": report.get("capital", {}),
            "valuation": report.get("valuation", {}),
            # 运行元信息
            "trace": state.get("trace", []),
            "result_path": state.get("result_path"),
        }

    @app.get("/api/reports/{ticker}/{report_date}", dependencies=[Depends(auth)])
    def read_report(ticker: str, report_date: str):
        path = saved_report_path(ticker, report_date)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"分析文档不存在: {path}")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------ 历史记录（中栏初始页）
    @app.get("/api/history", dependencies=[Depends(auth)])
    def list_history(limit: int = 200):
        """已落盘的分析清单（新→旧）：代码 / 名称 / 时间。

        先按 mtime 排序再截断，只解析最新的 ``limit`` 份文件：
        目录里堆了几百份报告时，列表仍要秒开。
        """
        base = results_dir()
        found: list[dict] = []
        if os.path.isdir(base):
            with os.scandir(base) as folders:
                for ticker_dir in folders:
                    if not ticker_dir.is_dir():
                        continue
                    with os.scandir(ticker_dir.path) as files:
                        for entry in files:
                            name = entry.name
                            if not (name.startswith("report_") and name.endswith(".json")):
                                continue
                            try:
                                stat = entry.stat()
                            except OSError:
                                continue
                            found.append({
                                "path": entry.path,
                                "folder": ticker_dir.name,
                                "file": name,
                                "mtime": stat.st_mtime,
                                "size": stat.st_size,
                            })

        found.sort(key=lambda item: item["mtime"], reverse=True)
        found = found[: max(1, min(int(limit), 500))]

        reports = []
        for item in found:
            company = _read_company_meta(item["path"])
            reports.append({
                # 文件里没有 company（旧版本或损坏）时退回目录名 / 文件名
                "ticker": company.get("ticker") or item["folder"],
                "name": company.get("name") or item["folder"],
                "report_date": company.get("report_date")
                or item["file"][len("report_"):-len(".json")],
                "market": company.get("market", ""),
                "saved_at": datetime.fromtimestamp(item["mtime"]).strftime("%Y-%m-%d %H:%M:%S"),
                "size": item["size"],
                "path": item["path"],
            })
        return {"dir": base, "count": len(reports), "reports": reports}

    @app.delete("/api/history/{ticker}/{report_date}", dependencies=[Depends(auth)])
    def delete_history(ticker: str, report_date: str):
        """删除一份已落盘报告（中栏历史列表的删除按钮）。"""
        path = saved_report_path(ticker, report_date)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"历史记录不存在: {path}")
        try:
            os.remove(path)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"删除失败：{exc}") from exc
        # 该标的的目录空了就顺手删掉，别在历史根目录留一堆空壳
        folder = os.path.dirname(path)
        with contextlib.suppress(OSError):
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
        return {"deleted": path}

    # ------------------------------------------------ 健康检查 + 静态页
    @app.get("/api/health")
    def health():
        return {"status": "ok", "token_required": guard}

    if os.path.isdir(STATIC_DIR):
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        def _stamp(name: str) -> str:
            """用文件 mtime 当版本号。

            浏览器（尤其 Edge）会缓存 style.css / app.js，改了前端却还显示旧样子，
            是最容易踩的坑。链接里带上 mtime，文件一变 URL 就变，一定拿新的。
            """
            try:
                return str(int(os.path.getmtime(os.path.join(STATIC_DIR, name))))
            except OSError:
                return "0"

        @app.get("/")
        def index():
            with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as fh:
                html = fh.read()
            for asset in ("style.css", "app.js"):
                html = html.replace(f"/static/{asset}", f"/static/{asset}?v={_stamp(asset)}")
            # 页面本身也可能被缓存，强制每次回源校验
            return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})

    return app

