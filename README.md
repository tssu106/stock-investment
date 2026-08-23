# KTrader — 한국형 멀티 에이전트 모의투자

DART 전자공시, 네이버 종목 뉴스, KRX 시세를 바탕으로 **여러 AI 에이전트가 토론하며 매매를 판단**하고,
모의로 사고팔아 **성과(점수)를 측정하고 데이터를 축적·분석**하는 프로그램입니다.
[TradingAgents](https://github.com/TauricResearch/TradingAgents)의 멀티 에이전트 구조를 참고해 한국 시장에 맞게
새로 작성했습니다. LLM은 **Claude(Anthropic)** 를 사용합니다.

> ⚠️ 이 도구는 **교육·연구용 모의투자**입니다. 개인 맞춤형 투자자문이 아니며, 투자 결정과 책임은 사용자 본인에게 있습니다.

---

## 멀티 에이전트 파이프라인

한 종목·한 시점에 대해 다음 순서로 판단합니다.

```
[데이터 수집]  DART 공시·재무 │ 네이버 뉴스 │ KRX 시세·지표
      │
      ▼
① 분석가 팀        공시분석가 · 뉴스분석가 · 기술분석가   → 각자 신호(BULLISH/BEARISH/NEUTRAL)
      │
      ▼
② 리서치 토론      강세연구원 ⇄ 약세연구원 (N라운드) → 리서치매니저 종합
      │
      ▼
③ 트레이더         매매안 제시 (방향 · 목표비중 · 근거)
      │
      ▼
④ 리스크 심의      공격적 · 중립 · 보수 위원 토론
      │
      ▼
⑤ 포트폴리오매니저  최종 결정 (매수/매도/보유 + 비중 + 확신)
      │
      ▼
⑥ 성찰/메모리      실제 결과로 교훈 도출 → 다음 판단에 주입
```

각 에이전트의 리포트·최종 결정·거래·성과는 모두 SQLite에 축적되어 사후 분석에 쓰입니다.

---

## 데이터 소스 (한국)

| 구분 | 소스 | 비고 |
|---|---|---|
| 공시·재무 | **DART OpenAPI** | 연간보고서 주요계정(YoY), 최근 공시 목록. 무료 인증키 필요 |
| 뉴스 | **네이버 모바일 주식 뉴스 API** | 종목별 제목+본문요약, 키 불필요 (검색 OpenAPI 폴백 지원) |
| 시세·지표 | **pykrx (KRX)** | 일봉 OHLCV, 이동평균·RSI·MACD·볼린저·거래량 |
| 벤치마크 | KOSPI 지수 (실패 시 KODEX 200 ETF 프록시) | 초과수익 계산 |

---

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -e .
```

Python 3.11+ 권장 (개발·검증은 3.14 에서 진행).

## 설정

1. `.env.example` 을 `.env` 로 복사하고 키를 채웁니다.

```
ANTHROPIC_API_KEY=sk-ant-...     # AI 분석 (모의 모드에선 불필요)
DART_API_KEY=...                 # https://opendart.fss.or.kr 무료 발급
NAVER_CLIENT_ID=                 # (선택) 뉴스 검색 폴백
NAVER_CLIENT_SECRET=
```

2. `config.yaml` 에서 모델·토론 라운드·워치리스트·초기자본·수수료를 조정합니다.

```yaml
llm:
  deep_model: "claude-sonnet-5"          # 토론/최종결정
  quick_model: "claude-haiku-4-5-20251001"  # 분석가/리스크
portfolio:
  initial_capital: 10000000              # 1천만원
  commission_rate: 0.00015               # 0.015%
  sell_tax_rate: 0.0018                  # 매도 거래세 0.18%
  max_position_weight: 0.20              # 종목당 최대 20%
watchlist: ["005930", "000660", ...]
```

---

## 사용법

```bash
# 한 종목 전체 에이전트 분석 (실제 Claude)
ktrader analyze 005930

# 비용 0 모의 모드 (키·토큰 없이 전 구간 확인)
ktrader analyze 005930 --mock

# 분석 결과를 모의매매로 즉시 반영
ktrader analyze 005930 --trade

# 워치리스트 순회 → 결정 + 모의매매 + 자산 스냅샷
ktrader run                # 실제 Claude
ktrader run --mock         # 모의

# 과거 구간 시뮬레이션 (기본 모의; --real 로 실제 LLM)
ktrader backtest --from 20260501 --to 20260701 --every 10

# 현재 포트폴리오
ktrader portfolio

# 사후평가 + 성과지표 + 에이전트 적중률
ktrader score

# 성숙된 결정에 대한 교훈(성찰) 생성/저장
ktrader reflect
```

### 실제 분석 예시 (삼성전자, 요약)

```
포트폴리오매니저 최종 결정: HOLD  목표비중 0.0%  확신 62%
 삼성전자는 영업이익률 개선과 110조원 규모 주주환원이라는 펀더멘털 강점을 보유하고 있으나,
 호재 발표 후 주가가 하락하며 재료 소멸 신호가 뚜렷하다. 60일선 하회, MACD 음전환, 거래량
 감소 등 기술적 약세 신호가 혼재되어 있고 ... (실데이터 기반 근거)
LLM 사용: 13콜, 약 $0.14
```

---

## 점수(스코어링) — "데이터를 쌓고 분석"

- **포트폴리오 성과**: 누적수익률, KOSPI(벤치마크) 대비 초과수익, 샤프비율, MDD
- **최종결정 적중률**: 매수/매도/보유 결정이 N일 뒤 실제 방향과 맞았는지
- **에이전트별 신호 적중률 / 평균 엣지**: 어떤 에이전트(공시/뉴스/기술/토론/리스크)가 잘 맞히는지

`reflection_horizon_days`(기본 5일) 뒤의 실제 종가로 자동 사후평가됩니다.

---

## 프로젝트 구조

```
ktrader/
  config.py            설정(.env + config.yaml)
  data/                market(pykrx)·indicators·dart·naver_news·cache
  llm/                 client(Anthropic + mock)·prompts(한국어)
  agents/              analysts·researchers·trader·risk·reflection
  engine/pipeline.py   전체 오케스트레이션
  portfolio/           paper_broker(수수료·세금)·scoring
  store/               db·schema.sql·repo (SQLite 축적)
  live/kis_broker.py   Phase 4 실거래 골격(미구현)
  cli.py               CLI 엔트리포인트
tests/                 단위 테스트 (pytest)
```

테스트: `pytest -q`

---

## 로드맵

- ✅ **Phase 0** 데이터 레이어 (DART·네이버·KRX + 캐시)
- ✅ **Phase 1** 멀티 에이전트 엔진 (분석가→토론→트레이더→리스크→PM)
- ✅ **Phase 2** 모의매매 + 점수 + 데이터 축적 + 성찰
- ⬜ **Phase 3** 웹 대시보드 (FastAPI/Streamlit): 포트폴리오·결정·리포트·차트
- ⬜ **Phase 4** 실제 투자 (한국투자증권 KIS API) — `live/kis_broker.py` 골격.
  기본 dry-run, 한도 강제, **사용자 직접 승인**. 모의 성적이 목표 기준을 넘긴 뒤 연결.

### 알려진 한계
- KRX 밸류에이션(PER/PBR)·지수 endpoint 가 간헐적으로 불안정 → PER/PBR은 best-effort, 지수는 ETF 프록시로 폴백.
- 백테스트에서 **뉴스/공시는 현재값**을 사용(시점 복원 아님). 주가/지표만 시점 기준. 뉴스 기반 백테스트는 참고용.

---

## 보안 주의
- API 키는 `.env` 에만 두세요 (`.gitignore` 로 보호됨). 코드·로그·커밋에 넣지 마세요.
- 키를 채팅/화면 등에 노출했다면 발급처에서 **폐기(rotate)** 후 재발급하세요.
