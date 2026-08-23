"""멀티 에이전트 파이프라인.

데이터 수집 → 분석가 팀 → 강세/약세 토론 → 리서치매니저 → 트레이더
→ 리스크 심의(공격/중립/보수) → 포트폴리오매니저(최종 결정).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from ..agents import analysts, researchers, risk, trader
from ..agents.base import AgentResult, ko
from ..config import Config
from ..data import indicators, market, naver_news
from ..data.cache import Cache
from ..data.dart import DartClient, default_range
from ..llm.client import LLMClient

StepCb = Callable[[str, AgentResult], None] | None


@dataclass
class DataBundle:
    ticker: str
    company: str
    run_date: str
    price: float
    tech_block: str
    dart_block: str
    news_block: str


@dataclass
class PipelineResult:
    ticker: str
    company: str
    run_date: str
    price: float
    reports: list[AgentResult] = field(default_factory=list)
    action: str = "HOLD"
    target_weight: float = 0.0
    confidence: float = 0.5
    rationale: str = ""
    bundle: DataBundle | None = None

    def report(self, role: str) -> AgentResult | None:
        return next((r for r in self.reports if r.role == role), None)


def gather_data(cfg: Config, ticker: str, run_date: str | None = None, *,
                price_store=None, as_of_backtest: bool = False) -> DataBundle:
    """데이터 수집.

    as_of_backtest=True 면 룩어헤드를 피한다: 재무는 run_date 이전 연간보고서만,
    과거 뉴스는 복원 불가라 제외, 시세는 price_store(있으면)로 시점 슬라이스.
    """
    ticker = str(ticker).zfill(6)
    run_date = market.norm_date(run_date) if run_date else market.today_str()
    company = market.get_name(ticker)

    if price_store is not None and price_store.has(ticker):
        ohlcv = price_store.recent_ohlcv(ticker, run_date, cfg.data.ohlcv_lookback_days)
    else:
        ohlcv = market.get_recent_ohlcv(ticker, cfg.data.ohlcv_lookback_days, end=run_date)
    snap = indicators.compute_snapshot(ohlcv)
    price = float(snap.get("close") or 0.0)

    tech_lines = [indicators.summarize(snap)]
    if not as_of_backtest:
        funda = market.get_fundamentals(ticker, run_date)
        if funda:
            tech_lines.append(
                "- 밸류에이션: " + ", ".join(f"{k} {v:,.2f}" for k, v in funda.items()))
    tech_block = "\n".join(tech_lines)

    cache = Cache(cfg.cache_dir, cfg.data.cache_ttl_hours)
    dart = DartClient(cfg.dart_api_key, cfg.cache_dir)
    d_start, d_end = default_range(cfg.data.disclosure_lookback_days, run_date)

    if as_of_backtest:
        rd = datetime.strptime(run_date, "%Y%m%d")
        as_of_year = rd.year - 1 if rd.month >= 4 else rd.year - 2
        dart_block = cache.get_or_set(
            f"dartsum:{ticker}:{run_date[:6]}",
            lambda: dart.summarize(ticker, d_start, d_end, as_of_year=as_of_year))
        news_block = "(백테스트 시점 모드: 과거 뉴스 복원 불가로 제외)"
    else:
        dart_block = cache.get_or_set(
            f"dartsum:{ticker}", lambda: dart.summarize(ticker, d_start, d_end))

        def _fetch_news() -> list:
            items = naver_news.fetch_finance_news(ticker, pages=cfg.data.news_pages)
            if not items and cfg.naver_client_id and cfg.naver_client_secret:
                items = naver_news.fetch_api_news(
                    company, cfg.naver_client_id, cfg.naver_client_secret)
            return items

        news = cache.get_or_set(f"news:{ticker}", _fetch_news)
        news_block = naver_news.summarize(news)

    return DataBundle(ticker, company, run_date, price, tech_block, dart_block, news_block)


def _reports_digest(reports: list[AgentResult]) -> str:
    lines = []
    for r in reports:
        conf = f" 확신={r.confidence:.0%}" if r.confidence else ""
        lines.append(f"[{ko(r.role)}] 신호={r.signal}{conf}\n{r.summary}")
    return "\n\n".join(lines)


def run_pipeline(cfg: Config, client: LLMClient, ticker: str,
                 run_date: str | None = None, *, position_state: str = "보유 없음",
                 memory: str = "", bundle: DataBundle | None = None,
                 on_step: StepCb = None) -> PipelineResult:
    if bundle is None:
        bundle = gather_data(cfg, ticker, run_date)

    reports: list[AgentResult] = []

    def emit(res: AgentResult) -> None:
        reports.append(res)
        if on_step:
            on_step(res.role, res)

    # 1) 분석가 팀
    emit(analysts.run_disclosure_analyst(
        client, bundle.company, bundle.ticker, bundle.run_date, bundle.dart_block, memory))
    emit(analysts.run_news_analyst(
        client, bundle.company, bundle.ticker, bundle.run_date, bundle.news_block, memory))
    emit(analysts.run_technical_analyst(
        client, bundle.company, bundle.ticker, bundle.run_date, bundle.tech_block, memory))

    analyst_digest = _reports_digest(reports)

    # 2) 강세 vs 약세 토론
    history_parts: list[str] = []
    for _ in range(max(1, cfg.engine.debate_rounds)):
        bull = researchers.run_researcher(
            client, "bull", bundle.company, bundle.ticker,
            analyst_digest, "\n\n".join(history_parts))
        history_parts.append(f"[강세연구원]\n{bull.summary}")
        emit(bull)
        bear = researchers.run_researcher(
            client, "bear", bundle.company, bundle.ticker,
            analyst_digest, "\n\n".join(history_parts))
        history_parts.append(f"[약세연구원]\n{bear.summary}")
        emit(bear)
    debate_history = "\n\n".join(history_parts)

    # 3) 리서치매니저 종합
    rm = researchers.run_research_manager(
        client, bundle.company, bundle.ticker, analyst_digest, debate_history)
    emit(rm)
    research_summary = f"견해={rm.signal} 확신={rm.confidence:.0%}\n{rm.summary}"

    # 4) 트레이더 매매안
    td = trader.run_trader(
        client, bundle.company, bundle.ticker, research_summary, position_state, memory)
    emit(td)
    trade_plan = (
        f"action={td.signal}, target_weight={td.data.get('target_weight', 0):.2%}, "
        f"확신={td.confidence:.0%}\n{td.summary}"
    )

    # 5) 리스크 심의(공격/중립/보수) 토론
    risk_history: list[str] = []
    for _ in range(max(1, cfg.engine.risk_rounds)):
        for role in risk.RISK_ROLES:
            rr = risk.run_risk_debator(
                client, role, bundle.company, bundle.ticker, trade_plan,
                research_summary, "\n\n".join(risk_history))
            risk_history.append(f"[{ko(role)}] 제안={rr.signal}\n{rr.summary}")
            emit(rr)
    risk_debate = "\n\n".join(risk_history)

    # 6) 포트폴리오매니저 최종 결정
    pm = risk.run_portfolio_manager(
        client, bundle.company, bundle.ticker, trade_plan, risk_debate,
        position_state, cfg.portfolio.max_position_weight)
    emit(pm)

    return PipelineResult(
        ticker=bundle.ticker, company=bundle.company, run_date=bundle.run_date,
        price=bundle.price, reports=reports,
        action=pm.signal, target_weight=float(pm.data.get("target_weight", 0.0)),
        confidence=pm.confidence, rationale=pm.summary, bundle=bundle,
    )


def persist_result(repo, result: PipelineResult, mock: bool) -> int:
    """파이프라인 결과(결정 + 모든 에이전트 리포트)를 DB에 저장하고 run_id 반환."""
    run_id = repo.save_run(
        ticker=result.ticker, name=result.company, run_date=result.run_date,
        action=result.action, target_weight=result.target_weight,
        confidence=result.confidence, price=result.price,
        rationale=result.rationale, mock=mock,
    )
    for r in result.reports:
        repo.save_agent_report(
            run_id, r.role, r.signal, r.confidence, r.summary, r.raw)
    return run_id
