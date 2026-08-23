"""전략 조합 그리드 백테스트.

규칙기반 팩터 점수를 (시점·종목)별로 한 번만 계산한 뒤, 여러 전략 프로필을
그 위에서 무료로 시뮬레이션해 성적을 순위화한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..config import Config
from ..data import market
from ..data.dart import DartClient
from ..data.pricestore import PriceStore
from ..strategy import factors, regime
from ..strategy.profile import Profile
from ..strategy.registry import default_grid
from ..strategy.simbroker import SimBroker


def _as_of_year(ds: str) -> int:
    dt = datetime.strptime(ds, "%Y%m%d")
    return dt.year - 1 if dt.month >= 4 else dt.year - 2


def factor_z_for_date(cfg: Config, ds: str, store: PriceStore, dart: DartClient,
                      fund_cache: dict | None = None) -> dict[str, dict]:
    """한 시점의 팩터 z-score (momentum/trend/lowvol/fundamental)."""
    fund_cache = fund_cache if fund_cache is not None else {}
    ay = _as_of_year(ds)
    raw = {f: {} for f in factors.FACTOR_NAMES}
    for tk in cfg.watchlist:
        df = store.recent_ohlcv(tk, ds, cfg.data.ohlcv_lookback_days)
        raw["momentum"][tk] = factors.momentum(df)
        raw["trend"][tk] = factors.trend(df)
        raw["lowvol"][tk] = factors.lowvol(df)
        key = (tk, ay)
        if key not in fund_cache:
            fund_cache[key] = factors.fundamental_score(dart, tk, ay)
        raw["fundamental"][tk] = fund_cache[key]
    return {f: factors.zscore(raw[f]) for f in factors.FACTOR_NAMES}


def precompute(cfg: Config, dates: list[str], store: PriceStore,
               bench: str) -> tuple[dict, dict, dict]:
    """시점별 팩터 z-score, 국면노출, 벤치마크 종가를 선계산."""
    dart = DartClient(cfg.dart_api_key, cfg.cache_dir)
    fund_cache: dict[tuple, float | None] = {}
    z_by_date, exposure_by_date, bench_close = {}, {}, {}
    for ds in dates:
        z_by_date[ds] = factor_z_for_date(cfg, ds, store, dart, fund_cache)
        exposure_by_date[ds] = regime.exposure(store, bench, ds)
        bench_close[ds] = store.price_on(bench, ds) or 0.0
    return z_by_date, exposure_by_date, bench_close


def simulate(cfg: Config, profile: Profile, dates: list[str], store: PriceStore,
             z_by_date: dict, exposure_by_date: dict) -> SimBroker:
    broker = SimBroker(cfg)
    max_w = cfg.portfolio.max_position_weight
    for ds in dates:
        price_map = {tk: p for tk in cfg.watchlist if (p := store.price_on(tk, ds))}
        if profile.use_stop:
            broker.apply_stop_loss(price_map)
        composite = profile.composite(z_by_date[ds])
        exposure = exposure_by_date[ds] if profile.use_regime else 1.0
        targets = profile.target_weights(composite, exposure, max_w)
        broker.rebalance(targets, price_map)
        broker.snapshot(ds, price_map)
    return broker


def run_gridtest(cfg: Config, frm: str, to: str, every: int,
                 profiles: list[Profile] | None = None) -> list[dict]:
    profiles = profiles or default_grid()
    start = datetime.strptime(market.norm_date(frm), "%Y%m%d")
    end = datetime.strptime(market.norm_date(to), "%Y%m%d")
    dates = []
    d = start
    while d <= end:
        dates.append(d.strftime("%Y%m%d"))
        d += timedelta(days=every)

    bench = market._BENCH_ETF.get(cfg.portfolio.benchmark, "069500")
    pre_start = (start - timedelta(days=cfg.data.ohlcv_lookback_days + 40)).strftime("%Y%m%d")
    pre_end = (end + timedelta(days=10)).strftime("%Y%m%d")
    store = PriceStore(cfg.watchlist + [bench], pre_start, pre_end)

    z_by_date, exposure_by_date, bench_close = precompute(cfg, dates, store, bench)
    bench_series = [bench_close[ds] for ds in dates if bench_close.get(ds)]

    results = []
    for p in profiles:
        broker = simulate(cfg, p, dates, store, z_by_date, exposure_by_date)
        m = broker.metrics(bench_series)
        results.append({
            "name": p.name, "weights": p.weights, "use_regime": p.use_regime,
            "top_n": p.top_n, **m,
        })
    results.sort(key=lambda r: r["return_pct"], reverse=True)
    return results
