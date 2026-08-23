"""KTrader 웹 대시보드 (FastAPI).

실행:  uvicorn ktrader.web.app:app --port 8848
또는:  ktrader-web   (pyproject scripts)

SQLite 에 축적된 결정/거래/성과를 읽어 JSON 으로 제공하고, 정적 대시보드를 서빙한다.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from ..agents.base import ko
from ..config import load_config
from ..data import market
from ..portfolio import scoring
from ..store.repo import Repo

app = FastAPI(title="KTrader 대시보드")
_HTML = Path(__file__).with_name("dashboard.html")


def _cfg():
    return load_config()


def _price_map(repo: Repo) -> dict[str, float]:
    pm: dict[str, float] = {}
    for p in repo.get_positions():
        px = market.get_price_on(p["ticker"])
        if px:
            pm[p["ticker"]] = px
    return pm


@app.get("/")
def index() -> FileResponse:
    # HTML 은 항상 최신을 받도록 캐시 비활성화 (편집 후 새로고침 시 즉시 반영)
    return FileResponse(_HTML, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/summary")
def api_summary(include_mock: bool = False) -> JSONResponse:
    cfg = _cfg()
    with Repo(cfg.db_path) as repo:
        pm = _price_map(repo)
        m = scoring.portfolio_metrics(cfg, repo, pm)
        acc = scoring.decision_accuracy(repo, include_mock=include_mock)
        m["decision_accuracy"] = acc["accuracy"]
        m["decision_n"] = acc["n"]
        m["decision_avg_return"] = acc["avg_return"]
    return JSONResponse(m)


@app.get("/api/positions")
def api_positions() -> JSONResponse:
    cfg = _cfg()
    with Repo(cfg.db_path) as repo:
        pm = _price_map(repo)
        out = []
        for p in repo.get_positions():
            px = pm.get(p["ticker"], p["avg_price"])
            pnl = (px / p["avg_price"] - 1) * 100 if p["avg_price"] else 0
            out.append({
                "ticker": p["ticker"], "name": p["name"], "qty": p["qty"],
                "avg_price": p["avg_price"], "price": px,
                "value": p["qty"] * px, "pnl_pct": round(pnl, 2),
            })
    return JSONResponse(out)


@app.get("/api/decisions")
def api_decisions(limit: int = 40) -> JSONResponse:
    cfg = _cfg()
    with Repo(cfg.db_path) as repo:
        rows = repo.recent_runs(limit=limit)
        out = [{
            "id": r["id"], "ticker": r["ticker"], "name": r["name"],
            "run_date": r["run_date"], "action": r["action"],
            "target_weight": r["target_weight"], "confidence": r["confidence"],
            "price": r["price"], "rationale": r["rationale"], "mock": r["mock"],
        } for r in rows]
    return JSONResponse(out)


@app.get("/api/run/{run_id}")
def api_run(run_id: int) -> JSONResponse:
    cfg = _cfg()
    with Repo(cfg.db_path) as repo:
        run = repo.get_run(run_id)
        if not run:
            return JSONResponse({"error": "not found"}, status_code=404)
        reports = [{
            "role": r["role"], "role_ko": ko(r["role"]), "signal": r["signal"],
            "confidence": r["confidence"], "summary": r["summary"],
        } for r in repo.get_reports(run_id)]
    return JSONResponse({"run": dict(run), "reports": reports})


@app.get("/api/agents")
def api_agents(include_mock: bool = False) -> JSONResponse:
    cfg = _cfg()
    with Repo(cfg.db_path) as repo:
        scoring.evaluate_pending_outcomes(cfg, repo)
        out = [{
            "role": s["role"], "role_ko": ko(s["role"]), "n": s["n"],
            "hit_rate": s["hit_rate"], "avg_edge": s["avg_edge"],
        } for s in scoring.agent_scores(repo, include_mock=include_mock)]
    return JSONResponse(out)


@app.get("/api/equity")
def api_equity() -> JSONResponse:
    cfg = _cfg()
    with Repo(cfg.db_path) as repo:
        rows = repo.equity_curve()
        out = [{"date": r["snapshot_date"], "equity": r["total_equity"],
                "cash": r["cash"], "holdings": r["holdings_value"]} for r in rows]
    return JSONResponse(out)


@app.get("/api/gridtest")
def api_gridtest() -> JSONResponse:
    """저장된 전략 조합 리더보드(gridtest_results.json)를 반환."""
    import json

    cfg = _cfg()
    p = cfg.data_dir / "gridtest_results.json"
    if not p.exists():
        return JSONResponse({"results": [], "meta": None})
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return JSONResponse({"results": [], "meta": None})
    return JSONResponse(data)


@app.get("/api/diagnose/{ticker}")
def api_diagnose(ticker: str, refresh: bool = False) -> JSONResponse:
    """종목 클릭 시 평가손익 원인 분석. 하루 단위로 캐시(반복 클릭 비용 절감)."""
    from ..data import market
    from ..data.cache import Cache
    from ..engine.diagnose import diagnose_position
    from ..llm.client import LLMClient

    cfg = _cfg()
    ticker = ticker.zfill(6)
    cache = Cache(cfg.cache_dir, ttl_hours=24)
    key = f"diag_web:{ticker}:{market.today_str()}"
    if not refresh:
        cached = cache.get(key)
        if cached:
            return JSONResponse(cached)

    with Repo(cfg.db_path) as repo:
        positions = {p["ticker"]: {"name": p["name"], "qty": p["qty"],
                                   "avg_price": p["avg_price"]}
                     for p in repo.get_positions()}
    client = LLMClient(cfg, mock=False)
    result = diagnose_position(cfg, client, ticker, positions)
    result["cost_usd"] = round(client.usage.cost_usd, 4)
    cache.set(key, result)
    return JSONResponse(result)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8848)


if __name__ == "__main__":
    main()
