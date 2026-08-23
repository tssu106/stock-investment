"""보유 종목 진단: 평가손익(수익/손실) 원인을 실제 데이터로 분석.

CLI(diagnose 명령)와 웹 대시보드가 공유한다.
"""

from __future__ import annotations

from ..agents.base import parse_json
from ..config import Config
from ..llm import prompts
from ..llm.client import LLMClient
from . import pipeline


def _won(v: float) -> str:
    return f"{v:,.0f}원"


def diagnose_position(cfg: Config, client: LLMClient, ticker: str,
                      positions: dict | None = None) -> dict:
    """한 종목의 평가손익 원인 분석 결과(dict)를 반환."""
    ticker = str(ticker).zfill(6)
    positions = positions or {}
    bundle = pipeline.gather_data(cfg, ticker)
    price = bundle.price
    pos = positions.get(ticker)

    pnl = None
    if pos and pos.get("avg_price"):
        pnl = (price / pos["avg_price"] - 1) * 100 if price else None
        pos_block = (f"진입평단 {_won(pos['avg_price'])}, 현재가 {_won(price)}, "
                     f"수량 {pos['qty']}주, 평가손익 {pnl:+.2f}%")
    else:
        pos_block = f"미보유(참고). 현재가 {_won(price)}"

    user = prompts.build_diagnose_user(
        bundle.company, ticker, pos_block, bundle.tech_block,
        bundle.dart_block, bundle.news_block)
    raw = client.chat("diagnose", prompts.SYSTEMS["diagnose"], user,
                      deep=True, max_tokens=3000)
    d = parse_json(raw)

    return {
        "ticker": ticker,
        "company": bundle.company,
        "price": price,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "pos_block": pos_block,
        "summary": d.get("summary"),
        "factors": d.get("factors", []),
        "fundamental": d.get("fundamental"),
        "news_flow": d.get("news_flow"),
        "technical": d.get("technical"),
        "outlook": d.get("outlook"),
        "raw": None if d else raw.strip(),  # 파싱 실패 시 원문
        "mock": client.mock,
    }
