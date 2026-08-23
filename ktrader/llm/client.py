"""Anthropic Claude 클라이언트 래퍼.

- deep/quick 모델 선택
- 토큰 사용량 및 대략 비용 집계
- 재시도
- mock 모드: API 키/비용 없이 정형화된 가짜 응답 반환 (전 구간 E2E 검증용)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

from ..config import Config

# 모델별 대략 단가 (USD / 1M tokens). 실제 단가는 변동될 수 있음 → 참고용.
_PRICING = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
_DEFAULT_PRICE = (3.0, 15.0)


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, model: str, in_tok: int, out_tok: int) -> None:
        pin, pout = _PRICING.get(model, _DEFAULT_PRICE)
        self.calls += 1
        self.input_tokens += in_tok
        self.output_tokens += out_tok
        self.cost_usd += in_tok / 1e6 * pin + out_tok / 1e6 * pout


class LLMClient:
    def __init__(self, config: Config, mock: bool = False):
        self.cfg = config
        self.mock = mock or not config.anthropic_api_key
        self.usage = Usage()
        self._client = None
        if not self.mock:
            import anthropic

            self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    def chat(self, role: str, system: str, user: str, *, deep: bool = True,
             max_tokens: int | None = None) -> str:
        if self.mock:
            return _mock_response(role, user)

        model = self.cfg.llm.deep_model if deep else self.cfg.llm.quick_model
        max_tokens = max_tokens or self.cfg.llm.max_tokens
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                self.usage.add(model, resp.usage.input_tokens, resp.usage.output_tokens)
                return "".join(
                    b.text for b in resp.content if getattr(b, "type", "") == "text"
                )
            except Exception as e:  # noqa: BLE001 - SDK 예외 다양
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM 호출 실패({role}): {last_err}")


# ---------------- Mock ----------------

def _seed(text: str) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest(), 16)


def _pick(options: list, text: str) -> object:
    return options[_seed(text) % len(options)]


def _mock_response(role: str, user: str) -> str:
    """역할별 정형화된 가짜 JSON. 입력 해시로 약간의 다양성 부여."""
    sig3 = _pick(["BULLISH", "BEARISH", "NEUTRAL"], user + role)
    conf = 0.5 + (_seed(user + role) % 40) / 100.0  # 0.5~0.89

    if role in ("disclosure", "news", "technical", "sentiment"):
        return json.dumps({
            "signal": sig3,
            "confidence": round(conf, 2),
            "summary": f"[모의 {role} 분석] 제공된 데이터 기준 {sig3} 신호로 판단.",
            "key_points": ["모의 근거1", "모의 근거2"],
        }, ensure_ascii=False)

    if role in ("bull", "bear"):
        return json.dumps({
            "argument": f"[모의 {role} 논거] 데이터를 근거로 한 방향성 주장.",
            "key_points": ["모의 포인트1", "모의 포인트2"],
        }, ensure_ascii=False)

    if role == "research_manager":
        return json.dumps({
            "stance": sig3,
            "confidence": round(conf, 2),
            "summary": "[모의 리서치매니저] 강세/약세 토론을 종합한 결론.",
        }, ensure_ascii=False)

    if role == "trader":
        action = _pick(["BUY", "HOLD", "SELL"], user)
        return json.dumps({
            "action": action,
            "target_weight": 0.1 if action == "BUY" else 0.0,
            "confidence": round(conf, 2),
            "rationale": "[모의 트레이더] 리서치 결론 기반 매매안.",
        }, ensure_ascii=False)

    if role in ("risk_aggressive", "risk_neutral", "risk_conservative"):
        return json.dumps({
            "suggested_action": _pick(["BUY", "HOLD", "SELL"], user + role),
            "view": f"[모의 {role}] 리스크 관점의 견해.",
            "key_points": ["모의 리스크1"],
        }, ensure_ascii=False)

    if role == "portfolio_manager":
        action = _pick(["BUY", "HOLD", "SELL"], user)
        return json.dumps({
            "action": action,
            "target_weight": 0.12 if action == "BUY" else (0.0 if action == "SELL" else 0.05),
            "confidence": round(conf, 2),
            "rationale": "[모의 포트폴리오매니저] 리스크 토론을 반영한 최종 결정.",
        }, ensure_ascii=False)

    if role == "reflection":
        return json.dumps({
            "lesson": "[모의 성찰] 이번 결정에서 배운 교훈 요약.",
        }, ensure_ascii=False)

    return json.dumps({"summary": f"[모의 {role}]"}, ensure_ascii=False)
