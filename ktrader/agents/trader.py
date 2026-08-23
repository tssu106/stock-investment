"""트레이더: 리서치 결론 + 보유상태 → 구체적 매매안."""

from __future__ import annotations

from ..llm import prompts
from ..llm.client import LLMClient
from .base import AgentResult, clamp01, norm_signal, parse_json

_ACTIONS = ("BUY", "SELL", "HOLD")


def run_trader(client: LLMClient, company: str, ticker: str, research_summary: str,
               position_state: str, memory: str = "") -> AgentResult:
    system = prompts.SYSTEMS["trader"]
    user = prompts.build_trader_user(company, ticker, research_summary,
                                     position_state, memory)
    raw = client.chat("trader", system, user, deep=True)
    d = parse_json(raw)
    return AgentResult(
        role="trader",
        signal=norm_signal(d.get("action"), _ACTIONS, "HOLD"),
        confidence=clamp01(d.get("confidence")),
        summary=str(d.get("rationale", "")).strip(),
        raw=raw,
        data={"target_weight": clamp01(d.get("target_weight"), 0.0)},
    )
