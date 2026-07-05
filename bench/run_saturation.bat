@echo off
REM ============================================================================
REM MABDT Engine - Saturation Probe
REM ============================================================================
REM Re-runs the two highest-rate columns of the sensitivity grid to probe
REM where the engine stops keeping up:
REM
REM   N    in {15, 50, 150, 500, 1000}
REM   rate in {3000, 10000}                 events/sec
REM
REM = 10 runs at 60 seconds each plus per-run shutdown overhead.
REM
REM IMPORTANT: this script APPENDS to the existing bench\results\summary.csv
REM rather than wiping it. run_sensitivity.bat already covers the full 5x6
REM grid, so use this script to re-run only the {3000, 10000} cells without
REM redoing the whole sweep. Archive or delete the matching rows in
REM summary.csv first, or the appended rows will duplicate them.
REM
REM Prerequisites: same as run_sensitivity.bat (.venv ready, MQTT broker up,
REM Mosquitto comfortable at the higher publish rates — for localhost
REM Mosquitto this is easy, but a remote broker may rate-limit).
REM
REM Disk note: at rate=10000 each per-event latency CSV reaches ~90 MB.
REM Plan for ~500 MB of new CSV files in bench\results\.
REM
REM Output:
REM   bench\results\summary.csv                 (10 rows appended)
REM   bench\results\N{N}_R{rate}_latency.csv   (one per run, ~90 MB at rate=10000)
REM   bench\results\N{N}_R{rate}_engine.log
REM   bench\results\scaling_latency.png         (regenerated, now spans more rates)
REM   bench\results\saturation.png              (regenerated, shows the ceiling)
REM ============================================================================

setlocal enabledelayedexpansion

cd /d "%~dp0.."

echo.
echo ============================================
echo MABDT Engine - Saturation Probe
echo ============================================
echo Grid: N in {15, 50, 150, 500, 1000} x rate in {3000, 10000}
echo Total: 10 runs at 60 seconds each
echo (appends to existing bench\results\summary.csv)
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

set DURATION=60
set /a TOTAL=10
set /a DONE=0

for %%N in (15 50 150 500 1000) do (
    for %%R in (3000 10000) do (
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
echo Saturation probe complete.
echo Results: bench\results\
echo ============================================
pause

endlocal
