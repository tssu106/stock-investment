"""설정 로딩: config.yaml + .env 를 읽어 타입이 있는 Config 객체로 제공."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# 프로젝트 루트 (이 파일 기준 두 단계 위: ktrader/config.py -> stock-investment/)
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "ktrader.db"


@dataclass
class LLMConfig:
    deep_model: str = "claude-sonnet-5"
    quick_model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 2000
    temperature: float = 0.4


@dataclass
class EngineConfig:
    debate_rounds: int = 2
    risk_rounds: int = 1
    reflection_horizon_days: int = 5
    use_sentiment_analyst: bool = False


@dataclass
class PortfolioConfig:
    initial_capital: float = 10_000_000
    commission_rate: float = 0.00015
    sell_tax_rate: float = 0.0018
    max_position_weight: float = 0.20
    benchmark: str = "1001"
    # 리스크/매매 규칙
    stop_loss_pct: float = -0.10     # 이 손실률 이하면 자동 손절 (0 이면 비활성)
    take_profit_pct: float = 0.0     # 이 수익률 이상이면 자동 익절 (0 이면 비활성)
    min_confidence: float = 0.0      # 신규 매수 최소 확신(미만이면 보류)


@dataclass
class DataConfig:
    news_pages: int = 2
    ohlcv_lookback_days: int = 120
    disclosure_lookback_days: int = 90
    cache_ttl_hours: int = 6


@dataclass
class StrategyConfig:
    # gridtest 리더보드에서 고른 규칙기반 전략명 (simrun 기본값)
    active_profile: str = "mom+trend+all"


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    data: DataConfig = field(default_factory=DataConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    watchlist: list[str] = field(default_factory=list)

    # 비밀 키 (.env)
    anthropic_api_key: str | None = None
    dart_api_key: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None

    # 경로
    root: Path = ROOT
    data_dir: Path = DATA_DIR
    cache_dir: Path = CACHE_DIR
    db_path: Path = DB_PATH

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    val = raw.get(key) or {}
    return val if isinstance(val, dict) else {}


def load_config(config_path: str | Path | None = None) -> Config:
    """config.yaml 과 .env 를 로딩해 Config 를 반환."""
    load_dotenv(ROOT / ".env")

    path = Path(config_path) if config_path else ROOT / "config.yaml"
    raw: dict[str, Any] = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # DB 경로 오버라이드 (여러 포트폴리오/실험 분리용): 환경변수 KTRADER_DB
    db_override = os.getenv("KTRADER_DB")
    db_path = Path(db_override) if db_override else DB_PATH

    cfg = Config(
        llm=LLMConfig(**_section(raw, "llm")),
        engine=EngineConfig(**_section(raw, "engine")),
        portfolio=PortfolioConfig(**_section(raw, "portfolio")),
        data=DataConfig(**_section(raw, "data")),
        strategy=StrategyConfig(**_section(raw, "strategy")),
        watchlist=[str(t) for t in (raw.get("watchlist") or [])],
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        dart_api_key=os.getenv("DART_API_KEY") or None,
        naver_client_id=os.getenv("NAVER_CLIENT_ID") or None,
        naver_client_secret=os.getenv("NAVER_CLIENT_SECRET") or None,
        db_path=db_path,
    )
    cfg.ensure_dirs()
    return cfg
