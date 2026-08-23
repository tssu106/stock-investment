"""DB 저장/조회 헬퍼."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repo:
    def __init__(self, db_path: Path):
        self.conn = db.connect(db_path)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Repo":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- state (key-value) ----
    def state_get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def state_set(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    # ---- 포트폴리오 현금 ----
    def get_cash(self) -> float | None:
        v = self.state_get("cash")
        return float(v) if v is not None else None

    def set_cash(self, amount: float) -> None:
        self.state_set("cash", amount)

    def init_portfolio(self, initial_capital: float) -> None:
        """최초 1회만 현금을 세팅한다."""
        if self.get_cash() is None:
            self.set_cash(initial_capital)
            self.state_set("initial_capital", initial_capital)

    # ---- runs (결정) ----
    def save_run(
        self,
        *,
        ticker: str,
        name: str,
        run_date: str,
        action: str,
        target_weight: float,
        confidence: float,
        price: float,
        rationale: str,
        mock: bool,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs(ticker, name, run_date, created_at, action, target_weight, "
            "confidence, price, rationale, mock) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ticker, name, run_date, _now(), action, target_weight, confidence,
             price, rationale, 1 if mock else 0),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def save_agent_report(
        self, run_id: int, role: str, signal: str, confidence: float,
        summary: str, raw: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO agent_reports(run_id, role, signal, confidence, summary, raw) "
            "VALUES(?,?,?,?,?,?)",
            (run_id, role, signal, confidence, summary, raw),
        )
        self.conn.commit()

    def get_run(self, run_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()

    def get_reports(self, run_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM agent_reports WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()

    def recent_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # ---- trades ----
    def record_trade(
        self, *, run_id: int | None, ticker: str, name: str, trade_date: str,
        side: str, qty: int, price: float, gross: float, commission: float,
        tax: float, cash_delta: float, cash_after: float,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO trades(run_id, ticker, name, trade_date, side, qty, price, "
            "gross, commission, tax, cash_delta, cash_after) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, ticker, name, trade_date, side, qty, price, gross,
             commission, tax, cash_delta, cash_after),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def all_trades(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM trades ORDER BY id").fetchall()

    # ---- positions ----
    def get_positions(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM positions WHERE qty > 0 ORDER BY ticker"
        ).fetchall()

    def get_position(self, ticker: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM positions WHERE ticker=?", (ticker,)
        ).fetchone()

    def upsert_position(self, ticker: str, name: str, qty: int, avg_price: float) -> None:
        if qty <= 0:
            self.conn.execute("DELETE FROM positions WHERE ticker=?", (ticker,))
        else:
            self.conn.execute(
                "INSERT INTO positions(ticker, name, qty, avg_price, updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET "
                "name=excluded.name, qty=excluded.qty, avg_price=excluded.avg_price, "
                "updated_at=excluded.updated_at",
                (ticker, name, qty, avg_price, _now()),
            )
        self.conn.commit()

    # ---- reflections (메모리) ----
    def add_reflection(
        self, run_id: int | None, ticker: str, situation: str, lesson: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO reflections(run_id, ticker, situation, lesson, created_at) "
            "VALUES(?,?,?,?,?)",
            (run_id, ticker, situation, lesson, _now()),
        )
        self.conn.commit()

    def get_reflections(self, ticker: str, limit: int = 5) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM reflections WHERE ticker=? ORDER BY id DESC LIMIT ?",
            (ticker, limit),
        ).fetchall()

    # ---- outcomes (사후 성과) ----
    def runs_without_outcome(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT r.* FROM runs r LEFT JOIN outcomes o ON o.run_id=r.id "
            "WHERE o.run_id IS NULL ORDER BY r.id"
        ).fetchall()

    def save_outcome(
        self, run_id: int, horizon_days: int, price_then: float,
        price_future: float, realized_return: float, correct: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO outcomes(run_id, horizon_days, price_then, price_future, "
            "realized_return, correct, evaluated_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET horizon_days=excluded.horizon_days, "
            "price_then=excluded.price_then, price_future=excluded.price_future, "
            "realized_return=excluded.realized_return, correct=excluded.correct, "
            "evaluated_at=excluded.evaluated_at",
            (run_id, horizon_days, price_then, price_future, realized_return,
             correct, _now()),
        )
        self.conn.commit()

    def agent_hit_rates(self, include_mock: bool = False) -> list[sqlite3.Row]:
        """에이전트(role)별 신호 적중률.

        각 에이전트의 신호(강세/약세/매수/매도)가 실제 사후 수익률 방향과
        일치했는지로 적중을 판정한다. avg_edge = 신호 방향으로의 평균 수익률.
        include_mock=False 면 실제(real) 결정만 집계(모의 데이터 오염 방지).
        """
        mock_clause = "" if include_mock else "AND r.mock = 0"
        return self.conn.execute(
            f"""
            SELECT ar.role,
                   COUNT(*) AS n,
                   AVG(CASE
                        WHEN ar.signal IN ('BULLISH','BUY') AND o.realized_return > 0 THEN 1.0
                        WHEN ar.signal IN ('BEARISH','SELL') AND o.realized_return < 0 THEN 1.0
                        ELSE 0.0 END) AS hit_rate,
                   AVG(CASE
                        WHEN ar.signal IN ('BULLISH','BUY') THEN o.realized_return
                        WHEN ar.signal IN ('BEARISH','SELL') THEN -o.realized_return
                        ELSE 0.0 END) AS avg_edge
            FROM agent_reports ar
            JOIN outcomes o ON o.run_id = ar.run_id
            JOIN runs r ON r.id = ar.run_id
            WHERE ar.signal IN ('BULLISH','BEARISH','BUY','SELL') {mock_clause}
            GROUP BY ar.role
            ORDER BY hit_rate DESC
            """
        ).fetchall()

    # ---- equity curve ----
    def snapshot_equity(
        self, snapshot_date: str, cash: float, holdings_value: float
    ) -> None:
        self.conn.execute(
            "INSERT INTO equity_curve(snapshot_date, cash, holdings_value, total_equity) "
            "VALUES(?,?,?,?) ON CONFLICT(snapshot_date) DO UPDATE SET "
            "cash=excluded.cash, holdings_value=excluded.holdings_value, "
            "total_equity=excluded.total_equity",
            (snapshot_date, cash, holdings_value, cash + holdings_value),
        )
        self.conn.commit()

    def equity_curve(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM equity_curve ORDER BY snapshot_date"
        ).fetchall()
