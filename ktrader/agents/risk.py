"""리스크 심의팀(공격/중립/보수) + 포트폴리오매니저(최종 의사결정)."""

from __future__ import annotations

from ..llm import prompts
from ..llm.client import LLMClient
from .base import AgentResult, clamp01, norm_signal, parse_json

_ACTIONS = ("BUY", "SELL", "HOLD")
RISK_ROLES = ("risk_aggressive", "risk_neutral", "risk_conservative")
_RISK_LABELS = {
    "risk_aggressive": "공격적",
    "risk_neutral": "중립적",
    "risk_conservative": "보수적",
}


def run_risk_debator(client: LLMClient, role: str, company: str, ticker: str,
                     trade_plan: str, research_summary: str,
                     debate_history: str) -> AgentResult:
    system = prompts.SYSTEMS[role]
    user = prompts.build_risk_user(company, ticker, trade_plan, research_summary,
                                   debate_history)
    raw = client.chat(role, system, user, deep=False)
    d = parse_json(raw)
    return AgentResult(
        role=role,
        signal=norm_signal(d.get("suggested_action"), _ACTIONS, "HOLD"),
        summary=str(d.get("view", "")).strip(),
        raw=raw,
        data={"key_points": d.get("key_points", []),
              "label": _RISK_LABELS.get(role, role)},
    )


def run_portfolio_manager(client: LLMClient, company: str, ticker: str,
                          trade_plan: str, risk_debate: str, position_state: str,
                          max_weight: float) -> AgentResult:
    system = prompts.SYSTEMS["portfolio_manager"]
    user = prompts.build_pm_user(company, ticker, trade_plan, risk_debate,
                                 position_state, max_weight)
    raw = client.chat("portfolio_manager", system, user, deep=True)
    d = parse_json(raw)
    weight = min(clamp01(d.get("target_weight"), 0.0), max_weight)
    return AgentResult(
        role="portfolio_manager",
        signal=norm_signal(d.get("action"), _ACTIONS, "HOLD"),
        confidence=clamp01(d.get("confidence")),
        summary=str(d.get("rationale", "")).strip(),
        raw=raw,
        data={"target_weight": weight},
    )
