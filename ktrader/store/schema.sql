-- KTrader SQLite 스키마

-- 키-값 상태 (현금, 포트폴리오 메타 등)
CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 파이프라인 1회 실행 = 1개의 결정 레코드
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    name          TEXT,
    run_date      TEXT NOT NULL,          -- 분석 기준일 YYYY-MM-DD
    created_at    TEXT NOT NULL,          -- 실제 실행 시각 ISO8601
    action        TEXT,                   -- BUY / SELL / HOLD
    target_weight REAL,                   -- 목표 비중 0~1
    confidence    REAL,                   -- 0~1
    price         REAL,                   -- 기준일 종가
    rationale     TEXT,                   -- 최종 근거 요약
    mock          INTEGER DEFAULT 0       -- 모의 LLM 여부
);
CREATE INDEX IF NOT EXISTS idx_runs_ticker_date ON runs(ticker, run_date);

-- 각 에이전트의 리포트
CREATE TABLE IF NOT EXISTS agent_reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL,
    role       TEXT NOT NULL,             -- disclosure/news/technical/bull/bear/research_manager/trader/risk_*/portfolio_manager
    signal     TEXT,                      -- BULLISH/BEARISH/NEUTRAL 또는 BUY/SELL/HOLD
    confidence REAL,
    summary    TEXT,
    raw        TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_reports_run ON agent_reports(run_id);

-- 모의 체결 거래
CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER,
    ticker       TEXT NOT NULL,
    name         TEXT,
    trade_date   TEXT NOT NULL,
    side         TEXT NOT NULL,           -- BUY / SELL
    qty          INTEGER NOT NULL,
    price        REAL NOT NULL,
    gross        REAL NOT NULL,           -- qty*price
    commission   REAL NOT NULL,
    tax          REAL NOT NULL,
    cash_delta   REAL NOT NULL,           -- 현금 증감(+매도 -매수)
    cash_after   REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);

-- 현재 보유 포지션
CREATE TABLE IF NOT EXISTS positions (
    ticker     TEXT PRIMARY KEY,
    name       TEXT,
    qty        INTEGER NOT NULL,
    avg_price  REAL NOT NULL,
    updated_at TEXT
);

-- 성찰(결과 기반 학습) 메모리
CREATE TABLE IF NOT EXISTS reflections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER,
    ticker     TEXT,
    situation  TEXT,
    lesson     TEXT,
    created_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_reflections_ticker ON reflections(ticker);

-- 결정별 사후 성과(적중 여부) - 에이전트 점수 산정용
CREATE TABLE IF NOT EXISTS outcomes (
    run_id          INTEGER PRIMARY KEY,
    horizon_days    INTEGER,
    price_then      REAL,
    price_future    REAL,
    realized_return REAL,                 -- 기간 수익률
    correct         INTEGER,              -- 방향 적중(1/0)
    evaluated_at    TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- 일별 포트폴리오 자산 스냅샷 (수익률/샤프/MDD 계산용)
CREATE TABLE IF NOT EXISTS equity_curve (
    snapshot_date  TEXT PRIMARY KEY,
    cash           REAL,
    holdings_value REAL,
    total_equity   REAL
);
