"""성찰 에이전트: 과거 결정 + 실제 결과 → 다음을 위한 교훈."""

from __future__ import annotations

from ..llm import prompts
from ..llm.client import LLMClient
from .base import parse_json


def run_reflection(client: LLMClient, company: str, ticker: str,
                   decision: str, outcome: str) -> str:
    system = prompts.SYSTEMS["reflection"]
    user = prompts.build_reflection_user(company, ticker, decision, outcome)
    raw = client.chat("reflection", system, user, deep=False)
    d = parse_json(raw)
    return str(d.get("lesson", "")).strip()
