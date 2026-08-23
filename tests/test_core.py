# -*- coding: utf-8 -*-
"""핵심 로직 단위 테스트 (LLM/네트워크 불필요)."""

import pandas as pd

from ktrader.agents.base import parse_json, clamp01, norm_signal
from ktrader.config import Config
from ktrader.data import indicators
from ktrader.portfolio.paper_broker import PaperBroker
from ktrader.portfolio.scoring import _direction_correct
from ktrader.store.repo import Repo


# ---- JSON 파서 ----
def test_parse_json_plain():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_codefence():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_embedded():
    assert parse_json('결론: {"signal":"BUY"} 입니다.') == {"signal": "BUY"}


def test_parse_json_invalid():
    assert parse_json("해당 없음") == {}


def test_clamp_and_signal():
    assert clamp01(1.5) == 1.0
    assert clamp01(-1) == 0.0
    assert clamp01("x", 0.3) == 0.3
    assert norm_signal("buy", ("BUY", "SELL"), "HOLD") == "BUY"
    assert norm_signal("xxx", ("BUY", "SELL"), "HOLD") == "HOLD"


# ---- 지표 ----
def test_sma():
    s = pd.Series(range(1, 31))
    assert indicators.sma(s, 5).iloc[-1] == sum([26, 27, 28, 29, 30]) / 5


def test_rsi_uptrend():
    s = pd.Series(range(1, 40))  # 계속 상승 → RSI 100 근처
    assert indicators.rsi(s, 14).iloc[-1] > 95


# ---- 모의 브로커: 수수료/거래세 ----
def _broker(tmp_path):
    cfg = Config()
    repo = Repo(tmp_path / "test.db")
    return cfg, repo, PaperBroker(cfg, repo)


def test_buy_applies_commission(tmp_path):
    cfg, repo, broker = _broker(tmp_path)
    start_cash = broker.cash
    fill = broker.buy("005930", "삼성전자", 100_000, 10, "20260101")
    assert fill.qty == 10
    assert fill.commission == round(1_000_000 * cfg.portfolio.commission_rate)
    assert fill.tax == 0.0
    assert broker.cash == start_cash - (1_000_000 + fill.commission)
    pos = broker.positions()["005930"]
    assert pos["qty"] == 10 and pos["avg_price"] == 100_000


def test_sell_applies_tax(tmp_path):
    cfg, repo, broker = _broker(tmp_path)
    broker.buy("005930", "삼성전자", 100_000, 10, "20260101")
    cash_before = broker.cash
    fill = broker.sell("005930", "삼성전자", 120_000, 5, "20260102")
    gross = 5 * 120_000
    expected_tax = round(gross * cfg.portfolio.sell_tax_rate)
    expected_comm = round(gross * cfg.portfolio.commission_rate)
    assert fill.tax == expected_tax
    assert broker.cash == cash_before + (gross - expected_comm - expected_tax)
    assert broker.positions()["005930"]["qty"] == 5


def test_buy_respects_cash_limit(tmp_path):
    cfg, repo, broker = _broker(tmp_path)
    # 자본 초과 주문 → 현금 한도 내로 축소
    fill = broker.buy("005930", "삼성전자", 100_000, 1000, "20260101")
    assert fill is not None
    assert broker.cash >= 0


# ---- 방향 적중 판정 ----
def test_direction_correct():
    assert _direction_correct("BUY", 5.0) == 1
    assert _direction_correct("BUY", -5.0) == 0
    assert _direction_correct("SELL", -5.0) == 1
    assert _direction_correct("HOLD", 1.0) == 1
    assert _direction_correct("HOLD", 10.0) == 0
