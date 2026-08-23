"""분석가 팀: 공시분석가 / 뉴스분석가 / 기술분석가 (+심리분석가 옵션)."""

from __future__ import annotations

from ..llm import prompts
from ..llm.client import LLMClient
from .base import AgentResult, clamp01, norm_signal, parse_json

_SIGNALS = ("BULLISH", "BEARISH", "NEUTRAL")


def _run(client: LLMClient, role: str, company: str, ticker: str,
         run_date: str, data_block: str, memory: str = "") -> AgentResult:
    system = prompts.SYSTEMS[role]
    user = prompts.build_analyst_user(company, ticker, run_date, data_block, memory)
    raw = client.chat(role, system, user, deep=False)
    d = parse_json(raw)
    return AgentResult(
        role=role,
        signal=norm_signal(d.get("signal"), _SIGNALS, "NEUTRAL"),
        confidence=clamp01(d.get("confidence")),
        summary=str(d.get("summary", "")).strip(),
        raw=raw,
        data={"key_points": d.get("key_points", [])},
    )


def run_disclosure_analyst(client, company, ticker, run_date, dart_block, memory=""):
    return _run(client, "disclosure", company, ticker, run_date, dart_block, memory)


def run_news_analyst(client, company, ticker, run_date, news_block, memory=""):
    return _run(client, "news", company, ticker, run_date, news_block, memory)


def run_technical_analyst(client, company, ticker, run_date, tech_block, memory=""):
    return _run(client, "technical", company, ticker, run_date, tech_block, memory)
