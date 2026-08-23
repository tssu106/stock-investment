"""한국투자증권(KIS) 실거래 브로커 어댑터 — Phase 4 골격.

이 파일은 실제 자금을 다루는 마지막 단계를 위한 **자리표시자(skeleton)**다.
PaperBroker 와 같은 인터페이스(cash, positions, buy, sell, apply_decision)를 갖추어,
엔진/CLI 가 브로커만 교체하면 실거래로 전환되도록 설계한다.

────────────────────────────────────────────────────────────────────────
안전 원칙 (반드시 준수)
────────────────────────────────────────────────────────────────────────
1. 기본은 항상 dry-run. 실주문은 `live=True` + 사용자의 명시적 확인이 있을 때만.
2. 1회 주문 금액/종목 비중/일일 손실 한도를 코드로 강제(하드 리밋)한다.
3. 실주문 실행은 **사용자 본인**이 트리거/승인한다. 자동/무인 실주문 금지.
4. 계좌/앱키는 .env 에만 두고 로그·커밋에 남기지 않는다.
5. 모의투자 성적(승률/초과수익/MDD)이 목표 기준을 만족하기 전에는 연결하지 않는다.

이 도구는 교육·연구용이며 개인 맞춤 투자자문이 아니다.

────────────────────────────────────────────────────────────────────────
구현 시 참고 (KIS Developers)
────────────────────────────────────────────────────────────────────────
- OAuth 토큰 발급:      POST /oauth2/tokenP
- 현금주문(현금매수/매도): POST /uapi/domestic-stock/v1/trading/order-cash
- 잔고조회:             GET  /uapi/domestic-stock/v1/trading/inquire-balance
- 현재가:               GET  /uapi/domestic-stock/v1/quotations/inquire-price
- 모의투자 도메인과 실전 도메인(및 TR ID)이 다르므로 환경 분리 필수.
"""

from __future__ import annotations

from ..config import Config


class KISBroker:
    """PaperBroker 와 동일 인터페이스를 목표로 하는 실거래 어댑터(미구현)."""

    def __init__(self, cfg: Config, *, live: bool = False,
                 max_order_krw: float = 1_000_000):
        self.cfg = cfg
        self.live = live          # False 면 dry-run
        self.max_order_krw = max_order_krw
        self._app_key = None      # .env: KIS_APP_KEY
        self._app_secret = None   # .env: KIS_APP_SECRET
        self._account = None      # .env: KIS_ACCOUNT_NO

    def _require_impl(self) -> None:
        raise NotImplementedError(
            "KIS 실거래는 Phase 4 에서 구현합니다. 지금은 모의투자(PaperBroker)를 사용하세요. "
            "실거래 연결 전 안전 원칙(모듈 상단)을 반드시 확인하세요."
        )

    @property
    def cash(self) -> float:
        self._require_impl()

    def positions(self) -> dict:
        self._require_impl()

    def buy(self, *args, **kwargs):
        self._require_impl()

    def sell(self, *args, **kwargs):
        self._require_impl()

    def apply_decision(self, *args, **kwargs):
        self._require_impl()
