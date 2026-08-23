"""시장 국면(레짐) 필터: 벤치마크 추세로 총 투자비중 상한을 조절."""

from __future__ import annotations


def exposure(store, benchmark_ticker: str, date: str,
             risk_on: float = 1.0, risk_off: float = 0.4, ma: int = 60) -> float:
    """벤치마크(예: KODEX200)가 이동평균 위면 risk_on, 아래면 risk_off 비중.

    store: PriceStore. 데이터 부족 시 위험중립(risk_on) 반환.
    """
    df = store.recent_ohlcv(benchmark_ticker, date, ma + 20)
    if df is None or len(df) < ma:
        return risk_on
    c = df["close"]
    sma = c.tail(ma).mean()
    if not sma:
        return risk_on
    return risk_on if c.iloc[-1] >= sma else risk_off
