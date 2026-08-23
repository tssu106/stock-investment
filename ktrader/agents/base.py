"""에이전트 공통 유틸: 결과 구조체와 LLM 출력(JSON) 파서."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    role: str
    signal: str = "NEUTRAL"       # BULLISH/BEARISH/NEUTRAL 또는 BUY/SELL/HOLD
    confidence: float = 0.5
    summary: str = ""
    raw: str = ""
    data: dict[str, Any] = field(default_factory=dict)


ROLE_KO = {
    "disclosure": "공시분석가",
    "news": "뉴스분석가",
    "technical": "기술분석가",
    "sentiment": "심리분석가",
    "bull": "강세연구원",
    "bear": "약세연구원",
    "research_manager": "리서치매니저",
    "trader": "트레이더",
    "risk_aggressive": "공격적리스크위원",
    "risk_neutral": "중립리스크위원",
    "risk_conservative": "보수적리스크위원",
    "portfolio_manager": "포트폴리오매니저",
}


def ko(role: str) -> str:
    return ROLE_KO.get(role, role)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json(text: str) -> dict[str, Any]:
    """LLM 응답에서 첫 JSON 객체를 추출/파싱. 실패 시 {}."""
    if not text:
        return {}
    t = text.strip()
    # ```json ... ``` 코드펜스 제거
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(t)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


def clamp01(v: Any, default: float = 0.5) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


def norm_signal(v: Any, allowed: tuple[str, ...], default: str) -> str:
    s = str(v or "").strip().upper()
    return s if s in allowed else default
