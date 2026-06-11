@echo off
REM ============================================================================
REM MABDT Engine - Full Sensitivity Grid
REM ============================================================================
REM Runs the full N x rate grid:
REM   N in {15, 50, 150, 500, 1000}
REM   rate in {30, 100, 300, 1000, 3000, 10000}  events/sec
REM = 30 runs at 60 seconds each plus per-run shutdown overhead.
REM Total wall time: ~50-70 minutes (depends on shutdown cost at large N
REM and disk I/O for the high-rate latency CSVs).
REM
REM Prerequisites: same as run_sweep.bat (.venv ready, MQTT broker up).
REM
REM Disk note: at rate=10000 each per-event latency CSV reaches ~90 MB.
REM Total per-run output for the high-rate cells alone is ~500 MB.
REM
REM Output:
REM   bench\results\summary.csv                       (one row per N x rate)
REM   bench\results\N{N}_R{rate}_latency.csv         (one file per run)
REM   bench\results\N{N}_R{rate}_engine.log
REM   bench\results\scaling_latency.png               (latency vs N, per rate)
REM   bench\results\saturation.png                    (actual vs target rate)
REM ============================================================================

setlocal enabledelayedexpansion

cd /d "%~dp0.."

echo.
echo ============================================
echo MABDT Engine - Full Sensitivity Grid
echo ============================================
echo Grid: N in {15, 50, 150, 500, 1000} x rate in {30, 100, 300, 1000, 3000, 10000}
echo Total: 30 runs at 60 seconds each
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at .venv
    echo Create it with:  python -m venv .venv
    echo Then install:    pip install -e ".[tiger]"
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo [INFO] Checking MQTT broker reachability at 127.0.0.1:8883...
python bench\check_broker.py --host 127.0.0.1 --port 8883
if errorlevel 1 (
    echo.
    echo [ERROR] MQTT broker not reachable.
    echo Start Mosquitto ^(or your broker^) on 127.0.0.1:8883 and retry.
    call deactivate
    pause
    exit /b 1
)
echo [OK] Broker reachable.
echo.

if exist "bench\results\summary.csv" (
    echo [INFO] Removing previous bench\results\summary.csv
    del /q "bench\results\summary.csv"
)
echo.

set DURATION=60
set /a TOTAL=30
set /a DONE=0

for %%N in (15 50 150 500 1000) do (
    for %%R in (30 100 300 1000 3000 10000) do (
        set /a DONE+=1
        echo ============================================
        echo [!DONE!/%TOTAL%] N=%%N at %%R eps for %DURATION%s
        echo ============================================
        python -m bench.benchmark --N %%N --rate %%R --duration %DURATION%
        if errorlevel 1 (
            echo [ERROR] Benchmark failed at N=%%N rate=%%R
            call deactivate
            pause
            exit /b 1
        )
        echo.
    )
)

echo ============================================
echo Aggregating results
echo ============================================
python -m bench.analyze
echo.

call deactivate

echo.
echo ============================================
echo Sensitivity sweep complete.
echo Results: bench\results\
echo ============================================
pause

endlocal
