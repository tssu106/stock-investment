@echo off
REM === KTrader 매일 장 마감 후 자동 실행 배치 ===
REM Windows 작업 스케줄러(KTrader Daily)가 평일 16:10에 호출.
REM 컴퓨터가 켜져 있고 로그인된 상태에서만 동작.

cd /d C:\workspace\stock-investment
set PYTHONUTF8=1
if not exist data\logs mkdir data\logs

echo ===================================================>> data\logs\daily.log
echo RUN %date% %time% >> data\logs\daily.log

REM (1) LLM 멀티 에이전트 실전 결정 → ktrader.db  (실제 Claude, 약 $1/거래일)
REM     비용을 원치 않으면 아래 한 줄을 REM 으로 주석 처리하세요.
".venv\Scripts\ktrader.exe" run >> data\logs\daily.log 2>&1

REM (2) 규칙기반 선택 전략 포워드 페이퍼트레이딩 → data\sim.db  (무료)
".venv\Scripts\ktrader.exe" simforward >> data\logs\daily.log 2>&1

echo DONE %date% %time% >> data\logs\daily.log

REM (3) 분석 완료 후 자동 종료 — 120초 유예. PC 사용 중이면 취소: shutdown /a
REM     절전으로 두고 싶으면 아래 줄을 다음으로 교체: rundll32.exe powrprof.dll,SetSuspendState 0,1,0
shutdown /s /t 120 /c "KTrader 일일 분석 완료 - 120초 후 자동 종료 (취소: shutdown /a)"
