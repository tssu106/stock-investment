"""모의 매매 브로커.

한국 시장 비용을 반영한다:
- 위탁수수료: 매수/매도 공통 commission_rate
- 증권거래세: 매도 시에만 sell_tax_rate
포지션/현금은 SQLite(repo)에 저장된다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Config
from ..store.repo import Repo


@dataclass
class Fill:
    ticker: str
    name: str
    side: str
    qty: int
    price: float
    gross: float
    commission: float
    tax: float
    cash_delta: float
    cash_after: float


class PaperBroker:
    def __init__(self, cfg: Config, repo: Repo):
        self.cfg = cfg
        self.repo = repo
        repo.init_portfolio(cfg.portfolio.initial_capital)

    # ---- 조회 ----
    @property
    def cash(self) -> float:
        return self.repo.get_cash() or 0.0

    def positions(self) -> dict[str, dict]:
        out = {}
        for p in self.repo.get_positions():
            out[p["ticker"]] = {"name": p["name"], "qty": p["qty"],
                                "avg_price": p["avg_price"]}
        return out

    def holdings_value(self, price_map: dict[str, float]) -> float:
        total = 0.0
        for tk, pos in self.positions().items():
            px = price_map.get(tk, pos["avg_price"])
            total += pos["qty"] * px
        return total

    def total_equity(self, price_map: dict[str, float]) -> float:
        return self.cash + self.holdings_value(price_map)

    # ---- 체결 ----
    def buy(self, ticker: str, name: str, price: float, qty: int,
            trade_date: str, run_id: int | None = None) -> Fill | None:
        if qty <= 0 or price <= 0:
            return None
        gross = qty * price
        commission = round(gross * self.cfg.portfolio.commission_rate)
        cost = gross + commission
        if cost > self.cash + 1e-6:
            # 현금 한도 내로 수량 축소
            qty = int(self.cash // (price * (1 + self.cfg.portfolio.commission_rate)))
            if qty <= 0:
                return None
            gross = qty * price
            commission = round(gross * self.cfg.portfolio.commission_rate)
            cost = gross + commission

        pos = self.repo.get_position(ticker)
        old_qty = pos["qty"] if pos else 0
        old_avg = pos["avg_price"] if pos else 0.0
        new_qty = old_qty + qty
        new_avg = (old_qty * old_avg + gross) / new_qty
        self.repo.upsert_position(ticker, name, new_qty, new_avg)

        cash_after = self.cash - cost
        self.repo.set_cash(cash_after)
        self.repo.record_trade(
            run_id=run_id, ticker=ticker, name=name, trade_date=trade_date,
            side="BUY", qty=qty, price=price, gross=gross, commission=commission,
            tax=0.0, cash_delta=-cost, cash_after=cash_after)
        return Fill(ticker, name, "BUY", qty, price, gross, commission, 0.0,
                    -cost, cash_after)

    def sell(self, ticker: str, name: str, price: float, qty: int,
             trade_date: str, run_id: int | None = None) -> Fill | None:
        pos = self.repo.get_position(ticker)
        if not pos or pos["qty"] <= 0 or price <= 0:
            return None
        qty = min(qty, pos["qty"])
        if qty <= 0:
            return None
        gross = qty * price
        commission = round(gross * self.cfg.portfolio.commission_rate)
        tax = round(gross * self.cfg.portfolio.sell_tax_rate)
        proceeds = gross - commission - tax

        new_qty = pos["qty"] - qty
        self.repo.upsert_position(ticker, name, new_qty, pos["avg_price"])

        cash_after = self.cash + proceeds
        self.repo.set_cash(cash_after)
        self.repo.record_trade(
            run_id=run_id, ticker=ticker, name=name, trade_date=trade_date,
            side="SELL", qty=qty, price=price, gross=gross, commission=commission,
            tax=tax, cash_delta=proceeds, cash_after=cash_after)
        return Fill(ticker, name, "SELL", qty, price, gross, commission, tax,
                    proceeds, cash_after)

    # ---- 결정 적용 ----
    def apply_decision(self, *, ticker: str, name: str, action: str,
                       target_weight: float, price: float, trade_date: str,
                       price_map: dict[str, float], run_id: int | None = None
                       ) -> Fill | None:
        """포트폴리오매니저 결정을 목표 비중에 맞춰 실제 체결로 옮긴다."""
        if price <= 0:
            return None
        pmap = dict(price_map)
        pmap[ticker] = price
        equity = self.total_equity(pmap)
        pos = self.repo.get_position(ticker)
        held_qty = pos["qty"] if pos else 0
        held_value = held_qty * price
        target_value = max(0.0, target_weight) * equity

        if action == "BUY":
            delta = target_value - held_value
            qty = int(delta // price)
            return self.buy(ticker, name, price, qty, trade_date, run_id) if qty > 0 else None
        if action == "SELL":
            if held_qty <= 0:
                return None
            # target_weight 만큼만 남기고 축소 (0 이면 전량 매도)
            keep_qty = int(target_value // price)
            sell_qty = held_qty - keep_qty
            return self.sell(ticker, name, price, sell_qty, trade_date, run_id) if sell_qty > 0 else None
        return None  # HOLD

    def rebalance(self, targets: dict[str, float], price_map: dict[str, float],
                  trade_date: str, name_map: dict[str, str],
                  run_id: int | None = None) -> list[Fill]:
        """목표 비중으로 리밸런싱 (매도 먼저 → 매수). 규칙기반 전략용."""
        equity = self.total_equity(price_map)
        max_w = self.cfg.portfolio.max_position_weight
        tgt_val = {tk: min(w, max_w) * equity for tk, w in targets.items()}
        fills: list[Fill] = []
        # 매도/축소 (목표에 없는 보유 포함)
        for tk, pos in list(self.positions().items()):
            px = price_map.get(tk)
            if not px:
                continue
            cur = pos["qty"] * px
            want = tgt_val.get(tk, 0.0)
            if cur - want > px:
                f = self.sell(tk, pos["name"], px, pos["qty"] - int(want // px),
                              trade_date, run_id)
                if f:
                    fills.append(f)
        # 매수/확대
        for tk, want in tgt_val.items():
            px = price_map.get(tk)
            if not px or want <= 0:
                continue
            pos = self.repo.get_position(tk)
            cur = (pos["qty"] if pos else 0) * px
            if want - cur > px:
                f = self.buy(tk, name_map.get(tk, tk), px, int((want - cur) // px),
                             trade_date, run_id)
                if f:
                    fills.append(f)
        return fills

    def apply_risk_rules(self, price_map: dict[str, float], trade_date: str,
                         run_id: int | None = None) -> list[tuple[str, Fill]]:
        """손절/익절 규칙에 걸리는 보유종목을 자동 청산. [(사유, Fill), ...] 반환."""
        sl = self.cfg.portfolio.stop_loss_pct
        tp = self.cfg.portfolio.take_profit_pct
        out: list[tuple[str, Fill]] = []
        for tk, pos in list(self.positions().items()):
            px = price_map.get(tk)
            if not px or not pos["avg_price"]:
                continue
            pnl = px / pos["avg_price"] - 1
            reason = "손절" if (sl < 0 and pnl <= sl) else (
                "익절" if (tp > 0 and pnl >= tp) else None)
            if reason:
                fill = self.sell(tk, pos["name"], px, pos["qty"], trade_date, run_id)
                if fill:
                    out.append((reason, fill))
        return out
