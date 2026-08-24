"""성과 스코어링: 포트폴리오 지표 + 결정 사후평가(에이전트 적중률)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from ..config import Config
from ..data import market
from ..store.repo import Repo


def _direction_correct(action: str, ret: float) -> int:
    if action == "BUY":
        return 1 if ret > 0 else 0
    if action == "SELL":
        return 1 if ret < 0 else 0
    # HOLD: 큰 변동이 없었으면 적절했다고 본다
    return 1 if abs(ret) < 3.0 else 0


def evaluate_pending_outcomes(cfg: Config, repo: Repo,
                              as_of: str | None = None, store=None) -> int:
    """성숙된(기준일+horizon 경과) 결정들의 실제 수익률/적중을 계산해 저장.

    store(PriceStore) 가 주어지면 시세를 메모리에서 슬라이스(빠름·행 방지).
    """
    horizon = cfg.engine.reflection_horizon_days
    today = datetime.strptime(market.norm_date(as_of), "%Y%m%d") if as_of else datetime.now()
    evaluated = 0

    for run in repo.runs_without_outcome():
        run_dt = datetime.strptime(market.norm_date(run["run_date"]), "%Y%m%d")
        future_dt = run_dt + timedelta(days=horizon)
        if future_dt > today:
            continue  # 아직 미성숙

        tk = run["ticker"]
        price_then = run["price"]
        if not price_then:
            price_then = (store.price_on(tk, run["run_date"]) if store
                          else market.get_price_on(tk, run["run_date"]))
        if not price_then:
            continue
        # horizon 이후 거래일 종가
        if store is not None:
            price_future = store.price_after(tk, future_dt.strftime("%Y%m%d"))
        else:
            price_future = market.get_price_on(
                tk, (future_dt + timedelta(days=4)).strftime("%Y%m%d"))
        if not price_future:
            continue

        ret = (price_future / price_then - 1) * 100
        correct = _direction_correct(run["action"], ret)
        repo.save_outcome(run["id"], horizon, price_then, price_future,
                          round(ret, 3), correct)
        evaluated += 1
    return evaluated


def portfolio_metrics(cfg: Config, repo: Repo, price_map: dict[str, float]) -> dict:
    initial = float(repo.state_get("initial_capital") or cfg.portfolio.initial_capital)
    cash = repo.get_cash() or 0.0
    holdings = 0.0
    for p in repo.get_positions():
        px = price_map.get(p["ticker"], p["avg_price"])
        holdings += p["qty"] * px
    equity = cash + holdings
    total_return = (equity / initial - 1) * 100 if initial else 0.0

    metrics = {
        "initial_capital": initial,
        "cash": cash,
        "holdings_value": holdings,
        "total_equity": equity,
        "total_return_pct": total_return,
        "sharpe": None,
        "mdd_pct": None,
        "benchmark_return_pct": None,
        "excess_return_pct": None,
    }

    curve = repo.equity_curve()
    if len(curve) >= 2:
        eq = [r["total_equity"] for r in curve]
        # MDD (스냅샷 2개부터 의미 있음)
        peak = eq[0]
        mdd = 0.0
        for v in eq:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        metrics["mdd_pct"] = round(mdd * 100, 2)

        # 벤치마크(KOSPI) 대비 초과수익 (2개부터 계산)
        start, end = curve[0]["snapshot_date"], curve[-1]["snapshot_date"]
        bench = market.get_benchmark_series(cfg.portfolio.benchmark,
                                            market.norm_date(start), market.norm_date(end))
        if len(bench) >= 2:
            bench_ret = (bench.iloc[-1] / bench.iloc[0] - 1) * 100
            metrics["benchmark_return_pct"] = round(bench_ret, 2)
            metrics["excess_return_pct"] = round(total_return - bench_ret, 2)

        # 샤프 (표본이 적으면 노이즈 → 스냅샷 3개 이상부터)
        if len(curve) >= 3:
            rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1]]
            if rets:
                mean = sum(rets) / len(rets)
                std = math.sqrt(sum((x - mean) ** 2 for x in rets) / len(rets))
                if std > 0:
                    metrics["sharpe"] = round(mean / std * math.sqrt(252), 3)

    return metrics


def curve_metrics(cfg: Config, repo: Repo) -> dict:
    """자산 곡선(equity_curve) 기반 성과 — 완료된 백테스트 비교용."""
    curve = repo.equity_curve()
    initial = float(repo.state_get("initial_capital") or cfg.portfolio.initial_capital)
    out = {"initial": initial, "final_equity": initial, "total_return_pct": 0.0,
           "benchmark_return_pct": None, "excess_return_pct": None,
           "sharpe": None, "mdd_pct": None, "points": len(curve)}
    if not curve:
        return out
    eq = [r["total_equity"] for r in curve]
    final = eq[-1]
    out["final_equity"] = final
    out["total_return_pct"] = round((final / initial - 1) * 100, 2) if initial else 0.0

    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1]]
    if rets:
        mean = sum(rets) / len(rets)
        std = math.sqrt(sum((x - mean) ** 2 for x in rets) / len(rets))
        if std > 0:
            out["sharpe"] = round(mean / std * math.sqrt(252), 3)
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    out["mdd_pct"] = round(mdd * 100, 2)

    bench = market.get_benchmark_series(
        cfg.portfolio.benchmark, market.norm_date(curve[0]["snapshot_date"]),
        market.norm_date(curve[-1]["snapshot_date"]))
    if len(bench) >= 2:
        br = (bench.iloc[-1] / bench.iloc[0] - 1) * 100
        out["benchmark_return_pct"] = round(br, 2)
        out["excess_return_pct"] = round(out["total_return_pct"] - br, 2)
    return out


def action_distribution(repo: Repo, include_mock: bool = True) -> dict:
    """결정(run) 액션 분포 (BUY/SELL/HOLD 건수)."""
    mock_clause = "" if include_mock else "AND mock = 0"
    rows = repo.conn.execute(
        f"SELECT action, COUNT(*) n FROM runs WHERE 1=1 {mock_clause} GROUP BY action"
    ).fetchall()
    return {r["action"]: r["n"] for r in rows}


def agent_scores(repo: Repo, include_mock: bool = False) -> list[dict]:
    rows = repo.agent_hit_rates(include_mock=include_mock)
    return [{"role": r["role"], "n": r["n"],
             "hit_rate": r["hit_rate"], "avg_edge": r["avg_edge"]} for r in rows]


def decision_accuracy(repo: Repo, include_mock: bool = False) -> dict:
    """전체 최종결정(run)의 적중률. include_mock=False 면 실제 결정만."""
    mock_clause = "" if include_mock else "AND r.mock = 0"
    row = repo.conn.execute(
        f"SELECT COUNT(*) n, AVG(o.correct) acc, AVG(o.realized_return) avg_ret "
        f"FROM outcomes o JOIN runs r ON r.id = o.run_id WHERE 1=1 {mock_clause}"
    ).fetchone()
    return {"n": row["n"], "accuracy": row["acc"], "avg_return": row["avg_ret"]}
