"""전략 조합 그리드 생성."""

from __future__ import annotations

from .profile import Profile

# 기본 팩터 조합 (이름 -> 가중치)
_BASE_COMBOS: dict[str, dict[str, float]] = {
    "momentum": {"momentum": 1.0},
    "trend": {"trend": 1.0},
    "lowvol": {"lowvol": 1.0},
    "fundamental": {"fundamental": 1.0},
    "mom+trend": {"momentum": 1.0, "trend": 1.0},
    "mom+fund": {"momentum": 1.0, "fundamental": 1.0},
    "mom+lowvol": {"momentum": 1.0, "lowvol": 1.0},
    "all4": {"momentum": 1.0, "trend": 1.0, "lowvol": 1.0, "fundamental": 1.0},
}


def default_grid() -> list[Profile]:
    """기본 조합 × 국면필터 × 집중(top3/전체) × 손절 그리드."""
    profiles: list[Profile] = []
    for base, weights in _BASE_COMBOS.items():
        for regime in (False, True):
            for top_n in (None, 3):
                for stop in (False, True):
                    name = base
                    name += "+R" if regime else ""
                    name += "+top3" if top_n else "+all"
                    name += "+SL" if stop else ""
                    profiles.append(Profile(name, dict(weights), use_regime=regime,
                                            top_n=top_n, use_stop=stop))
    return profiles


def profile_by_name(name: str) -> Profile | None:
    for p in default_grid():
        if p.name == name:
            return p
    return None
