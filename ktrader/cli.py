"""KTrader CLI (Typer).

명령:
  analyze  <ticker>   한 종목 멀티 에이전트 분석 → 리포트 + 추천
  run                 워치리스트 순회 → 결정 + 모의 매매 + 자산 스냅샷
  backtest            과거 구간 시뮬레이션(주가/지표는 시점기준, 뉴스/공시는 현재값)
  portfolio           현재 보유/현금/평가손익
  score               사후평가 + 성과지표 + 에이전트 적중률
  reflect             성숙된 결정에 대한 교훈 생성/저장
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agents.base import ko
from .config import load_config

# Windows 콘솔 UTF-8 강제
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = typer.Typer(add_completion=False, help="한국형 멀티 에이전트 모의투자 (KTrader)")
console = Console()

_SIGNAL_COLOR = {
    "BULLISH": "green", "BUY": "green",
    "BEARISH": "red", "SELL": "red",
    "NEUTRAL": "yellow", "HOLD": "yellow",
}


def _won(v: float) -> str:
    return f"{v:,.0f}원"


def _sig(s: str) -> str:
    return f"[{_SIGNAL_COLOR.get(s, 'white')}]{s}[/]"


def _ctx(mock: bool):
    from .llm.client import LLMClient
    from .store.repo import Repo

    cfg = load_config()
    repo = Repo(cfg.db_path)
    client = LLMClient(cfg, mock=mock)
    if client.mock and not mock:
        console.print("[yellow]ANTHROPIC_API_KEY 없음 → 모의(mock) 모드로 실행합니다.[/]")
    return cfg, repo, client


def _memory_text(repo, ticker: str, limit: int = 3) -> str:
    rows = repo.get_reflections(ticker, limit=limit)
    return "\n".join(f"- {r['lesson']}" for r in rows if r["lesson"])


def _print_result(result, client) -> None:
    header = (f"[bold]{result.company}[/] ({result.ticker})  "
              f"기준일 {result.run_date}  현재가 {_won(result.price)}")
    console.print(Panel(header, expand=False))

    groups = [
        ("분석가 팀", ["disclosure", "news", "technical"]),
        ("리서치 토론", ["bull", "bear", "research_manager"]),
        ("트레이더", ["trader"]),
        ("리스크 심의", ["risk_aggressive", "risk_neutral", "risk_conservative"]),
    ]
    for title, roles in groups:
        console.print(f"\n[bold cyan]■ {title}[/]")
        for r in result.reports:
            if r.role not in roles:
                continue
            conf = f" · 확신 {r.confidence:.0%}" if r.confidence else ""
            console.print(f"  [bold]{ko(r.role)}[/] {_sig(r.signal)}{conf}")
            if r.summary:
                console.print(f"    {r.summary}")

    final = (f"최종 결정: {_sig(result.action)}  "
             f"목표비중 {result.target_weight:.1%}  확신 {result.confidence:.0%}\n\n"
             f"{result.rationale}")
    color = _SIGNAL_COLOR.get(result.action, "white")
    console.print(Panel(final, title="[bold]포트폴리오매니저 최종 결정[/]",
                        border_style=color))

    if not client.mock:
        u = client.usage
        console.print(f"[dim]LLM 사용: {u.calls}콜, "
                      f"입력 {u.input_tokens:,} / 출력 {u.output_tokens:,} 토큰, "
                      f"약 ${u.cost_usd:.3f}[/]")
    else:
        console.print("[dim](모의 모드 — 실제 LLM 미사용)[/]")


def _position_state(broker, ticker: str, price: float) -> str:
    pos = broker.positions().get(ticker)
    if pos:
        pnl = (price / pos["avg_price"] - 1) * 100 if pos["avg_price"] else 0
        held = (f"보유 {pos['qty']}주, 평단 {_won(pos['avg_price'])}, "
                f"평가손익 {pnl:+.1f}%")
    else:
        held = "미보유"
    return f"{held}\n현금 {_won(broker.cash)}"


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="종목코드 6자리 (예: 005930)"),
    date: str = typer.Option(None, "--date", "-d", help="기준일 YYYYMMDD (기본: 오늘)"),
    mock: bool = typer.Option(False, "--mock", "-m", help="모의 LLM 사용(비용 0)"),
    trade: bool = typer.Option(False, "--trade", help="결정을 모의매매로 즉시 반영"),
):
    """한 종목을 멀티 에이전트로 분석한다."""
    from .engine import pipeline
    from .portfolio.paper_broker import PaperBroker

    cfg, repo, client = _ctx(mock)
    broker = PaperBroker(cfg, repo)
    ticker = ticker.zfill(6)

    with console.status("[cyan]데이터 수집 및 에이전트 분석 중...[/]"):
        bundle = pipeline.gather_data(cfg, ticker, date)
        pos_state = _position_state(broker, ticker, bundle.price)
        result = pipeline.run_pipeline(
            cfg, client, ticker, date, position_state=pos_state,
            memory=_memory_text(repo, ticker), bundle=bundle)

    run_id = pipeline.persist_result(repo, result, mock=client.mock)
    _print_result(result, client)

    if trade and result.price > 0:
        fill = broker.apply_decision(
            ticker=ticker, name=result.company, action=result.action,
            target_weight=result.target_weight, price=result.price,
            trade_date=result.run_date, price_map={ticker: result.price}, run_id=run_id)
        if fill:
            console.print(f"[bold]체결:[/] {fill.side} {fill.qty}주 @ {_won(fill.price)} "
                          f"(수수료 {_won(fill.commission)}, 세금 {_won(fill.tax)})")
        else:
            console.print("[dim]체결 없음 (HOLD 또는 조건 미충족)[/]")
    repo.close()


@app.command()
def run(
    date: str = typer.Option(None, "--date", "-d", help="기준일 YYYYMMDD"),
    mock: bool = typer.Option(False, "--mock", "-m"),
    no_trade: bool = typer.Option(False, "--no-trade", help="분석만, 매매 미반영"),
):
    """워치리스트를 순회하며 하루치 결정 + 모의매매."""
    from .engine import pipeline
    from .portfolio.paper_broker import PaperBroker

    cfg, repo, client = _ctx(mock)
    broker = PaperBroker(cfg, repo)
    trade_date = _norm_or_today(date)

    # 현재 보유 + 워치리스트 종목의 시세를 먼저 확보
    from .data import market
    tickers = list(dict.fromkeys(cfg.watchlist + list(broker.positions())))
    price_map: dict[str, float] = {}
    for tk in broker.positions():
        px = market.get_price_on(tk, trade_date)
        if px:
            price_map[tk] = px

    # 손절/익절 규칙 먼저 적용
    if not no_trade:
        for reason, f in broker.apply_risk_rules(price_map, trade_date):
            console.print(f"[magenta]■ {reason}[/] {f.name} {f.qty}주 매도 @ {_won(f.price)}")

    table = Table(title=f"워치리스트 결정 ({trade_date})")
    for c in ("종목", "코드", "결정", "비중", "확신", "체결"):
        table.add_column(c)

    for tk in cfg.watchlist:
        with console.status(f"[cyan]{tk} 분석 중...[/]"):
            bundle = pipeline.gather_data(cfg, tk, date)
            price_map[tk] = bundle.price
            pos_state = _position_state(broker, tk, bundle.price)
            result = pipeline.run_pipeline(
                cfg, client, tk, date, position_state=pos_state,
                memory=_memory_text(repo, tk), bundle=bundle)
        run_id = pipeline.persist_result(repo, result, mock=client.mock)

        # 확신 임계: 확신 낮은 신규 매수는 보류
        action = result.action
        if action == "BUY" and result.confidence < cfg.portfolio.min_confidence:
            action = "HOLD"

        filled = "-"
        if not no_trade and result.price > 0:
            fill = broker.apply_decision(
                ticker=tk, name=result.company, action=action,
                target_weight=result.target_weight, price=result.price,
                trade_date=trade_date, price_map=price_map, run_id=run_id)
            if fill:
                filled = f"{fill.side} {fill.qty}주"
        label = action + ("*" if action != result.action else "")
        table.add_row(result.company, tk, label,
                      f"{result.target_weight:.0%}", f"{result.confidence:.0%}", filled)

    console.print(table)

    # 자산 스냅샷
    broker.repo.snapshot_equity(
        _iso(trade_date), broker.cash, broker.holdings_value(price_map))
    _print_portfolio(cfg, repo, broker, price_map)
    if not client.mock:
        u = client.usage
        console.print(f"[dim]LLM 사용: {u.calls}콜, 약 ${u.cost_usd:.3f}[/]")
    repo.close()


@app.command()
def backtest(
    frm: str = typer.Option(..., "--from", help="시작일 YYYYMMDD"),
    to: str = typer.Option(..., "--to", help="종료일 YYYYMMDD"),
    every: int = typer.Option(5, "--every", help="며칠 간격으로 결정할지"),
    mock: bool = typer.Option(True, "--mock/--real", help="기본 모의(비용 0). --real 로 실제 LLM"),
):
    """과거 구간 시뮬레이션. 시세·재무는 시점 기준(룩어헤드 제거), 뉴스는 과거 복원 불가로 제외."""
    from .data import market
    from .data.pricestore import PriceStore
    from .engine import pipeline
    from .portfolio import scoring
    from .portfolio.paper_broker import PaperBroker

    cfg, repo, client = _ctx(mock)
    broker = PaperBroker(cfg, repo)

    start = datetime.strptime(market.norm_date(frm), "%Y%m%d")
    end = datetime.strptime(market.norm_date(to), "%Y%m%d")
    if not mock:
        console.print("[yellow]주의: --real 백테스트는 (시점 수 × 종목 수 × 약 13콜)만큼 비용이 발생합니다.[/]")

    dates = []
    d = start
    while d <= end:
        dates.append(d.strftime("%Y%m%d"))
        d += timedelta(days=every)

    # 시세 일괄 적재: 종목별 1회 조회 → 시점별 슬라이스 (속도↑·행 방지·룩어헤드 없음)
    horizon = cfg.engine.reflection_horizon_days
    pre_start = (start - timedelta(days=cfg.data.ohlcv_lookback_days + 40)).strftime("%Y%m%d")
    pre_end = (end + timedelta(days=horizon + 10)).strftime("%Y%m%d")
    tickers = list(dict.fromkeys(cfg.watchlist + list(broker.positions())))
    with console.status(f"[cyan]시세 적재 중... ({len(tickers)}종목)[/]"):
        store = PriceStore(tickers, pre_start, pre_end)

    console.print(f"[cyan]백테스트: {len(dates)}개 시점 × {len(cfg.watchlist)}종목 (시점 기준)[/]")
    price_map: dict[str, float] = {}
    for ds in dates:
        price_map = {tk: p for tk in tickers if (p := store.price_on(tk, ds))}
        for reason, f in broker.apply_risk_rules(price_map, ds):
            console.print(f"  [magenta]{reason}[/] {f.name} {f.qty}주 @ {_won(f.price)}")
        for tk in cfg.watchlist:
            bundle = pipeline.gather_data(cfg, tk, ds, price_store=store,
                                          as_of_backtest=True)
            if bundle.price <= 0:
                continue
            price_map[tk] = bundle.price
            pos_state = _position_state(broker, tk, bundle.price)
            result = pipeline.run_pipeline(
                cfg, client, tk, ds, position_state=pos_state,
                memory=_memory_text(repo, tk), bundle=bundle)
            run_id = pipeline.persist_result(repo, result, mock=client.mock)
            action = result.action
            if action == "BUY" and result.confidence < cfg.portfolio.min_confidence:
                action = "HOLD"
            broker.apply_decision(
                ticker=tk, name=result.company, action=action,
                target_weight=result.target_weight, price=result.price,
                trade_date=ds, price_map=price_map, run_id=run_id)
        broker.repo.snapshot_equity(_iso(ds), broker.cash,
                                    broker.holdings_value(price_map))
        console.print(f"  {ds} 완료 · 총자산 {_won(broker.total_equity(price_map))}")

    n = scoring.evaluate_pending_outcomes(cfg, repo, store=store)
    console.print(f"[green]사후평가 완료: {n}건[/]")
    _print_score(cfg, repo, broker, price_map, include_mock=mock)
    repo.close()


@app.command()
def portfolio(mock: bool = typer.Option(False, "--mock", "-m")):
    """현재 포트폴리오 상태."""
    from .data import market
    from .portfolio.paper_broker import PaperBroker

    cfg, repo, _ = _ctx(mock=True)
    broker = PaperBroker(cfg, repo)
    price_map = {}
    for tk in broker.positions():
        px = market.get_price_on(tk, None)
        if px:
            price_map[tk] = px
    _print_portfolio(cfg, repo, broker, price_map)
    repo.close()


@app.command()
def score(include_mock: bool = typer.Option(False, "--include-mock",
                                            help="모의(mock) 결정도 집계에 포함")):
    """사후평가 + 성과지표 + 에이전트 적중률 (기본: 실제 결정만)."""
    from .data import market
    from .portfolio import scoring
    from .portfolio.paper_broker import PaperBroker

    cfg, repo, _ = _ctx(mock=True)
    broker = PaperBroker(cfg, repo)
    n = scoring.evaluate_pending_outcomes(cfg, repo)
    console.print(f"[green]신규 사후평가: {n}건[/]")
    price_map = {}
    for tk in broker.positions():
        px = market.get_price_on(tk, None)
        if px:
            price_map[tk] = px
    _print_score(cfg, repo, broker, price_map, include_mock=include_mock)
    repo.close()


@app.command()
def reflect(mock: bool = typer.Option(False, "--mock", "-m")):
    """성숙된 결정에 대해 성찰(교훈)을 생성/저장한다."""
    from .agents.reflection import run_reflection
    from .portfolio import scoring

    cfg, repo, client = _ctx(mock)
    scoring.evaluate_pending_outcomes(cfg, repo)
    rows = repo.conn.execute(
        "SELECT r.*, o.realized_return, o.correct FROM runs r "
        "JOIN outcomes o ON o.run_id=r.id "
        "LEFT JOIN reflections rf ON rf.run_id=r.id "
        "WHERE rf.id IS NULL ORDER BY r.id"
    ).fetchall()
    console.print(f"[cyan]성찰 대상 {len(rows)}건[/]")
    for row in rows:
        decision = f"결정 {row['action']}, 비중 {row['target_weight']:.0%}: {row['rationale']}"
        outcome = (f"{cfg.engine.reflection_horizon_days}일 후 수익률 "
                   f"{row['realized_return']:+.2f}%, 적중 {'O' if row['correct'] else 'X'}")
        lesson = run_reflection(client, row["name"], row["ticker"], decision, outcome)
        if lesson:
            repo.add_reflection(row["id"], row["ticker"], outcome, lesson)
            console.print(f"  [bold]{row['name']}[/]: {lesson}")
    repo.close()


@app.command()
def diagnose(
    tickers: list[str] = typer.Argument(None, help="분석할 종목코드(생략 시 손실 보유종목 전체)"),
    mock: bool = typer.Option(False, "--mock", "-m"),
    threshold: float = typer.Option(0.0, "--threshold", "-t",
                                    help="이 수익률(%) 미만 보유종목을 분석 (기본 0=손실)"),
):
    """보유 종목의 평가손익(수익/손실) 원인을 실제 데이터로 분석한다."""
    from .data import market
    from .engine.diagnose import diagnose_position
    from .portfolio.paper_broker import PaperBroker

    cfg, repo, client = _ctx(mock)
    broker = PaperBroker(cfg, repo)
    positions = broker.positions()

    targets: list[str] = []
    if tickers:
        targets = [t.zfill(6) for t in tickers]
    else:
        for tk, pos in positions.items():
            px = market.get_price_on(tk)
            if px and pos["avg_price"] and (px / pos["avg_price"] - 1) * 100 < threshold:
                targets.append(tk)

    if not targets:
        console.print("[yellow]분석 대상이 없습니다 (조건에 맞는 보유종목 없음).[/]")
        repo.close()
        return

    console.print(f"[cyan]원인 분석 대상: {len(targets)}종목[/]\n")
    for tk in targets:
        with console.status(f"[cyan]{tk} 원인 분석 중...[/]"):
            r = diagnose_position(cfg, client, tk, positions)
        color = "green" if (r["pnl"] or 0) >= 0 else "red"
        console.print(Panel(f"[bold]{r['company']}[/] ({tk})\n{r['pos_block']}",
                            border_style=color, expand=False))
        if r.get("summary") or r.get("factors"):
            if r.get("summary"):
                console.print(f"[bold]■ 핵심 원인[/]\n{r['summary']}")
            if r.get("factors"):
                console.print("\n[bold]■ 세부 요인[/]")
                for f in r["factors"]:
                    console.print(f"  • {f}")
            for key, label in [("fundamental", "펀더멘털"), ("news_flow", "뉴스·수급"),
                               ("technical", "기술적"), ("outlook", "향후 관점")]:
                if r.get(key):
                    console.print(f"\n[bold]■ {label}[/]\n{r[key]}")
        elif r.get("raw"):
            console.print(f"[yellow](구조화 파싱 실패 — 원문)[/]\n{r['raw']}")
        console.print()

    if not client.mock:
        console.print(f"[dim]LLM 사용: {client.usage.calls}콜, 약 ${client.usage.cost_usd:.3f}[/]")
    repo.close()


@app.command()
def compare(
    a: str = typer.Option(..., "--a", help="DB 경로 A (예: data/mock_bt.db)"),
    b: str = typer.Option(..., "--b", help="DB 경로 B (예: data/real_bt.db)"),
    label_a: str = typer.Option("랜덤(mock)", "--label-a"),
    label_b: str = typer.Option("AI(real)", "--label-b"),
):
    """두 백테스트 DB의 성적을 나란히 비교 (예: 랜덤 vs AI)."""
    from pathlib import Path

    from .portfolio import scoring
    from .store.repo import Repo

    cfg = load_config()
    ra, rb = Repo(Path(a)), Repo(Path(b))
    ma, mb = scoring.curve_metrics(cfg, ra), scoring.curve_metrics(cfg, rb)
    acca = scoring.decision_accuracy(ra, include_mock=True)
    accb = scoring.decision_accuracy(rb, include_mock=True)
    da, db_ = scoring.action_distribution(ra), scoring.action_distribution(rb)

    def pct(v):
        return "N/A" if v is None else f"{v:+.2f}%"

    def acc(a):
        return f"{a['accuracy']:.0%} (n={a['n']})" if a["n"] and a["accuracy"] is not None else "N/A"

    def dist(d):
        return " / ".join(f"{k} {d.get(k, 0)}" for k in ("BUY", "SELL", "HOLD"))

    table = Table(title="백테스트 비교 (랜덤 vs AI)")
    table.add_column("지표")
    table.add_column(label_a, justify="right")
    table.add_column(label_b, justify="right")
    table.add_row("최종 자산", _won(ma["final_equity"]), _won(mb["final_equity"]))
    table.add_row("수익률", pct(ma["total_return_pct"]), pct(mb["total_return_pct"]))
    table.add_row("KOSPI 대비 초과", pct(ma["excess_return_pct"]), pct(mb["excess_return_pct"]))
    table.add_row("벤치마크(KOSPI)", pct(ma["benchmark_return_pct"]), pct(mb["benchmark_return_pct"]))
    table.add_row("샤프", str(ma["sharpe"]), str(mb["sharpe"]))
    table.add_row("MDD", pct(ma["mdd_pct"]), pct(mb["mdd_pct"]))
    table.add_row("결정 적중률", acc(acca), acc(accb))
    table.add_row("결정 분포", dist(da), dist(db_))
    console.print(table)
    ra.close()
    rb.close()


# ---------------- 출력 헬퍼 ----------------

def _print_portfolio(cfg, repo, broker, price_map) -> None:
    table = Table(title="보유 포지션")
    for c in ("종목", "코드", "수량", "평단", "현재가", "평가손익"):
        table.add_column(c)
    for tk, pos in broker.positions().items():
        px = price_map.get(tk, pos["avg_price"])
        pnl = (px / pos["avg_price"] - 1) * 100 if pos["avg_price"] else 0
        color = "green" if pnl >= 0 else "red"
        table.add_row(pos["name"], tk, f"{pos['qty']:,}", _won(pos["avg_price"]),
                      _won(px), f"[{color}]{pnl:+.1f}%[/]")
    console.print(table)

    equity = broker.total_equity(price_map)
    initial = float(repo.state_get("initial_capital") or cfg.portfolio.initial_capital)
    ret = (equity / initial - 1) * 100 if initial else 0
    color = "green" if ret >= 0 else "red"
    console.print(Panel(
        f"현금 {_won(broker.cash)}  |  주식평가 {_won(broker.holdings_value(price_map))}  |  "
        f"총자산 {_won(equity)}\n초기자본 {_won(initial)}  →  수익률 [{color}]{ret:+.2f}%[/]",
        title="[bold]자산 요약[/]", expand=False))


def _print_score(cfg, repo, broker, price_map=None, include_mock=False) -> None:
    from .portfolio import scoring
    price_map = price_map or {}
    m = scoring.portfolio_metrics(cfg, repo, price_map)

    def pct(v):
        return "N/A" if v is None else f"{v:+.2f}%"

    console.print(Panel(
        f"총자산 {_won(m['total_equity'])}  |  수익률 {pct(m['total_return_pct'])}\n"
        f"벤치마크(KOSPI) {pct(m['benchmark_return_pct'])}  |  "
        f"초과수익 {pct(m['excess_return_pct'])}\n"
        f"샤프 {m['sharpe'] if m['sharpe'] is not None else 'N/A'}  |  "
        f"MDD {pct(m['mdd_pct'])}",
        title="[bold]포트폴리오 성과[/]", expand=False))

    acc = scoring.decision_accuracy(repo, include_mock=include_mock)
    if acc["n"]:
        tag = "" if include_mock else " · 실제 결정만"
        console.print(f"최종결정 적중률: {acc['accuracy']:.0%} "
                      f"(n={acc['n']}, 평균수익 {acc['avg_return']:+.2f}%{tag})")

    scores = scoring.agent_scores(repo, include_mock=include_mock)
    if scores:
        table = Table(title="에이전트별 신호 적중률")
        for c in ("에이전트", "표본", "적중률", "평균엣지"):
            table.add_column(c)
        for s in scores:
            table.add_row(ko(s["role"]), str(s["n"]),
                          f"{s['hit_rate']:.0%}" if s["hit_rate"] is not None else "N/A",
                          f"{s['avg_edge']:+.2f}%" if s["avg_edge"] is not None else "N/A")
        console.print(table)


# ---------------- 날짜 유틸 ----------------

def _norm_or_today(date: str | None) -> str:
    from .data import market
    return market.norm_date(date) if date else market.today_str()


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


if __name__ == "__main__":
    app()
