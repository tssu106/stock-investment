"""리서치 팀: 강세연구원 / 약세연구원 / 리서치매니저(종합)."""

from __future__ import annotations

from ..llm import prompts
from ..llm.client import LLMClient
from .base import AgentResult, clamp01, norm_signal, parse_json

_STANCES = ("BULLISH", "BEARISH", "NEUTRAL")


def run_researcher(client: LLMClient, side_role: str, company: str, ticker: str,
                   analyst_reports: str, debate_history: str) -> AgentResult:
    label = "강세론(매수)" if side_role == "bull" else "약세론(매도/관망)"
    system = prompts.SYSTEMS[side_role]
    user = prompts.build_debate_user(company, ticker, analyst_reports,
                                     debate_history, label)
    raw = client.chat(side_role, system, user, deep=True)
    d = parse_json(raw)
    return AgentResult(
        role=side_role,
        signal="BULLISH" if side_role == "bull" else "BEARISH",
        summary=str(d.get("argument", "")).strip(),
        raw=raw,
        data={"key_points": d.get("key_points", [])},
    )


def run_research_manager(client: LLMClient, company: str, ticker: str,
                         analyst_reports: str, debate_history: str) -> AgentResult:
    system = prompts.SYSTEMS["research_manager"]
    user = prompts.build_research_manager_user(company, ticker, analyst_reports,
                                               debate_history)
    raw = client.chat("research_manager", system, user, deep=True)
    d = parse_json(raw)
    return AgentResult(
        role="research_manager",
        signal=norm_signal(d.get("stance"), _STANCES, "NEUTRAL"),
        confidence=clamp01(d.get("confidence")),
        summary=str(d.get("summary", "")).strip(),
        raw=raw,
    )
