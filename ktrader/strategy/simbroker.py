"""그리드 백테스트용 경량 인메모리 브로커 (DB 불필요, 빠름).

한국 시장 비용(위탁수수료 매수/매도, 매도 거래세)을 그대로 반영한다.
"""

from __future__ import annotations

import math

from ..config import Config


class SimBroker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cash = float(cfg.portfolio.initial_capital)
        self.initial = self.cash
        self.pos: dict[str, dict] = {}  # ticker -> {qty, avg}
        self.curve: list[tuple[str, float]] = []  # (date, equity)
        self.trades = 0

    # ---- 체결 ----
    def _buy(self, tk: str, px: float, qty: int) -> None:
        if qty <= 0 or px <= 0:
            return
        gross = qty * px
        commission = round(gross * self.cfg.portfolio.commission_rate)
        cost = gross + commission
        if cost > self.cash:
            qty = int(self.cash // (px * (1 + self.cfg.portfolio.commission_rate)))
            if qty <= 0:
                return
            gross = qty * px
            commission = round(gross * self.cfg.portfolio.commission_rate)
            cost = gross + commission
        p = self.pos.get(tk, {"qty": 0, "avg": 0.0})
        new_qty = p["qty"] + qty
        p["avg"] = (p["qty"] * p["avg"] + gross) / new_qty
        p["qty"] = new_qty
        self.pos[tk] = p
        self.cash -= cost
        self.trades += 1

    def _sell(self, tk: str, px: float, qty: int) -> None:
        p = self.pos.get(tk)
        if not p or p["qty"] <= 0 or px <= 0:
            return
        qty = min(qty, p["qty"])
        gross = qty * px
        commission = round(gross * self.cfg.portfolio.commission_rate)
        tax = round(gross * self.cfg.portfolio.sell_tax_rate)
        self.cash += gross - commission - tax
        p["qty"] -= qty
        if p["qty"] <= 0:
            del self.pos[tk]
        self.trades += 1

    # ---- 평가 ----
    def equity(self, price_map: dict[str, float]) -> float:
        v = self.cash
        for tk, p in self.pos.items():
            v += p["qty"] * price_map.get(tk, p["avg"])
        return v

    # ---- 규칙 ----
    def apply_stop_loss(self, price_map: dict[str, float]) -> None:
        sl = self.cfg.portfolio.stop_loss_pct
        if sl >= 0:
            return
        for tk, p in list(self.pos.items()):
            px = price_map.get(tk)
            if px and p["avg"] and (px / p["avg"] - 1) <= sl:
                self._sell(tk, px, p["qty"])

    def rebalance(self, targets: dict[str, float], price_map: dict[str, float]) -> None:
        """목표 비중으로 리밸런싱 (매도 먼저 → 매수)."""
        eq = self.equity(price_map)
        max_w = self.cfg.portfolio.max_position_weight
        tgt_val = {tk: min(w, max_w) * eq for tk, w in targets.items()}

        # 매도/축소 (목표에 없는 보유 포함)
        for tk, p in list(self.pos.items()):
            px = price_map.get(tk)
            if not px:
                continue
            cur = p["qty"] * px
            want = tgt_val.get(tk, 0.0)
            if cur - want > px:
                self._sell(tk, px, p["qty"] - int(want // px))
        # 매수/확대
        for tk, want in tgt_val.items():
            px = price_map.get(tk)
            if not px or want <= 0:
                continue
            cur = self.pos.get(tk, {"qty": 0})["qty"] * px
            if want - cur > px:
                self._buy(tk, px, int((want - cur) // px))

    def snapshot(self, date: str, price_map: dict[str, float]) -> None:
        self.curve.append((date, self.equity(price_map)))

    # ---- 성과 ----
    def metrics(self, benchmark: list[float] | None = None) -> dict:
        eq = [v for _, v in self.curve]
        out = {"final": eq[-1] if eq else self.initial,
               "return_pct": 0.0, "sharpe": None, "mdd_pct": None,
               "excess_pct": None, "trades": self.trades}
        if not eq:
            return out
        out["return_pct"] = round((eq[-1] / self.initial - 1) * 100, 2)
        rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1]]
        if rets:
            m = sum(rets) / len(rets)
            sd = math.sqrt(sum((x - m) ** 2 for x in rets) / len(rets))
            if sd > 0:
                out["sharpe"] = round(m / sd * math.sqrt(252), 2)
        peak, mdd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        out["mdd_pct"] = round(mdd * 100, 2)
        if benchmark and len(benchmark) >= 2 and benchmark[0]:
            br = (benchmark[-1] / benchmark[0] - 1) * 100
            out["excess_pct"] = round(out["return_pct"] - br, 2)
            out["benchmark_pct"] = round(br, 2)
        return out
