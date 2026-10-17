@echo off
REM === KTrader daily run (weekday 16:10 via Task Scheduler "KTrader Daily") ===
cd /d C:\workspace\stock-investment
set PYTHONUTF8=1
if not exist data\logs mkdir data\logs
echo =================================================== >> data\logs\daily.log
echo RUN %date% %time% >> data\logs\daily.log
REM (1) LLM multi-agent live decisions -> ktrader.db  (real Claude, ~$1/trading day)
REM     To skip the cost, put REM in front of the next line.
".venv\Scripts\ktrader.exe" run >> data\logs\daily.log 2>&1
REM (2) Rule-based selected strategy forward paper trading -> data\sim.db  (free)
".venv\Scripts\ktrader.exe" simforward >> data\logs\daily.log 2>&1
echo DONE %date% %time% >> data\logs\daily.log
REM (3) One-time skip: if flag file exists, skip shutdown and consume the flag.
if exist data\skip_shutdown.flag ( del data\skip_shutdown.flag & echo SHUTDOWN SKIPPED %date% %time% >> data\logs\daily.log & goto :eof )
REM (4) Auto shutdown 120s after analysis. If using the PC: run  shutdown /a
shutdown /s /t 120 /c "KTrader daily done - shutdown in 120s (cancel: shutdown /a)"
