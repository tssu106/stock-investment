"""전략 프로필: 팩터 가중 조합 + 토글(국면필터/랭킹집중/손절)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Profile:
    name: str
    weights: dict[str, float] = field(default_factory=dict)  # factor -> weight
    use_regime: bool = False       # 시장 국면 필터
    top_n: int | None = None       # 상위 N개 집중 (None=양수 점수 전체)
    use_stop: bool = False         # 손절 사용

    def composite(self, factor_z: dict[str, dict[str, float]]) -> dict[str, float]:
        """팩터별 z-score를 가중 합산해 종목별 종합점수."""
        tickers: set[str] = set()
        for f in self.weights:
            tickers |= set(factor_z.get(f, {}).keys())
        out = {}
        for tk in tickers:
            out[tk] = sum(w * factor_z.get(f, {}).get(tk, 0.0)
                          for f, w in self.weights.items())
        return out

    def target_weights(self, composite: dict[str, float], exposure: float,
                       max_weight: float) -> dict[str, float]:
        """종합점수 → 목표 비중. 양수 점수만, top_n 집중, 등가중×국면노출."""
        ranked = sorted(composite.items(), key=lambda x: x[1], reverse=True)
        picks = [tk for tk, s in ranked if s > 0]
        if self.top_n:
            picks = picks[: self.top_n]
        if not picks:
            return {}
        per = min(exposure / len(picks), max_weight)
        return {tk: per for tk in picks}
