"""규칙기반 팩터 신호 (시점 기준·LLM 불필요).

각 팩터는 종목별 원점수(raw)를 만들고, 같은 시점 유니버스 내에서 z-score 로 표준화한다.
- momentum : 60일 수익률
- trend    : 60일 이동평균 대비 이격도
- lowvol   : 최근 20일 변동성의 음수(낮을수록 고득점)
- fundamental : DART 성장/재무건전성 (as_of 기준, 룩어헤드 없음)
- supply   : 외국인/기관 수급 (KRX 점검 중이면 None → 자동 비활성)
"""

from __future__ import annotations

import math

import pandas as pd

FACTOR_NAMES = ["momentum", "trend", "lowvol", "fundamental"]


def momentum(df: pd.DataFrame) -> float | None:
    if df is None or len(df) < 61:
        return None
    c = df["close"]
    base = c.iloc[-61]
    return (c.iloc[-1] / base - 1) * 100 if base else None


def trend(df: pd.DataFrame) -> float | None:
    if df is None or len(df) < 60:
        return None
    c = df["close"]
    sma60 = c.tail(60).mean()
    return (c.iloc[-1] / sma60 - 1) * 100 if sma60 else None


def lowvol(df: pd.DataFrame) -> float | None:
    if df is None or len(df) < 21:
        return None
    r = df["close"].pct_change().tail(20)
    s = r.std()
    return -float(s) * 100 if s == s else None  # 낮은 변동성 = 높은 점수


def fundamental_score(dart, ticker: str, as_of_year: int | None) -> float | None:
    """DART 성장/재무건전성 프록시: 영업이익·매출 성장 - 과도한 부채."""
    fin = dart.latest_financials(ticker, as_of_year=as_of_year)
    acc = fin.get("accounts", {})
    if not acc:
        return None
    score, parts = 0.0, 0
    op = acc.get("영업이익", {})
    rev = acc.get("매출액", {})
    if op.get("yoy") is not None:
        score += op["yoy"]; parts += 1
    if rev.get("yoy") is not None:
        score += rev["yoy"] * 0.5; parts += 1
    liab, eq = acc.get("부채총계", {}), acc.get("자본총계", {})
    if liab.get("current") and eq.get("current"):
        debt_ratio = liab["current"] / eq["current"] * 100
        score -= max(0.0, debt_ratio - 100) * 0.1  # 부채비율 100% 초과분 패널티
    return score if parts else None


def supply_score(ticker: str, date: str) -> float | None:
    """외국인/기관 순매수 팩터 (플레이스홀더).

    현재 KRX 투자자별 매매 endpoint 가 불안정해 None 반환 → z-score 에서 중립 처리.
    KRX 복구 시 pykrx get_market_trading_value_by_date(detail=True) 로 구현.
    """
    return None


def zscore(scores: dict[str, float | None]) -> dict[str, float]:
    """유니버스 내 z-score 표준화. None 은 0(중립)."""
    vals = [v for v in scores.values() if v is not None]
    if len(vals) < 2:
        return {k: 0.0 for k in scores}
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))
    if sd == 0:
        return {k: 0.0 for k in scores}
    return {k: ((v - m) / sd if v is not None else 0.0) for k, v in scores.items()}
