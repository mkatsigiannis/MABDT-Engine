@echo off
REM ============================================================================
REM MABDT Engine - Scaling Benchmark Sweep
REM ============================================================================
REM Runs the full N in {15, 50, 150, 500, 1000} sweep at 30 events/sec for
REM 60 seconds per point, then prints the summary table and writes the
REM scaling plot.
REM
REM Prerequisites:
REM   - .venv created and populated (pip install -e ".[tiger]")
REM   - psutil and matplotlib available in the venv
REM   - MQTT broker reachable at 127.0.0.1:8883
REM
REM Output:
REM   bench\results\summary.csv
REM   bench\results\N{N}_latency.csv      (one per N)
REM   bench\results\N{N}_engine.log       (one per N)
REM   bench\results\scaling_latency.png
REM
REM For a single point with custom args:
REM     python -m bench.benchmark --N 500 --rate 100 --duration 60
REM ============================================================================

setlocal enabledelayedexpansion

REM This script lives in <repo_root>\bench\. Move CWD to the repo root so
REM .venv, the bench package, and the results path all resolve the same
REM way whether the .bat was launched from the repo root, from bench\,
REM or by a double-click.
cd /d "%~dp0.."

echo.
echo ============================================
echo MABDT Engine - Scaling Benchmark Sweep
echo ============================================
echo.

REM Check virtual environment
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at .venv
    echo Create it with:  python -m venv .venv
    echo Then install:    pip install -e ".[tiger]"
    pause
    exit /b 1
)

REM Activate venv
call .venv\Scripts\activate.bat

REM Confirm the MQTT broker is reachable before spending six minutes
REM publishing into the void. Matches the host/port the benchmark uses
REM by default (127.0.0.1:8883).
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

REM Clear the previous summary so the sweep starts fresh. Per-N CSVs are
REM overwritten when their N is rerun, so we only need to wipe the
REM aggregate file.
if exist "bench\results\summary.csv" (
    echo [INFO] Removing previous bench\results\summary.csv
    del /q "bench\results\summary.csv"
)
echo.

set RATE=30
set DURATION=60

for %%N in (15 50 150 500 1000) do (
    echo ============================================
    echo Running N=%%N at %RATE% eps for %DURATION%s
    echo ============================================
    python -m bench.benchmark --N %%N --rate %RATE% --duration %DURATION%
    if errorlevel 1 (
        echo [ERROR] Benchmark failed at N=%%N
        call deactivate
        pause
        exit /b 1
    )
    echo.
)

echo ============================================
echo Aggregating results
echo ============================================
python -m bench.analyze
echo.

call deactivate

echo.
echo ============================================
echo Sweep complete.
echo Results: bench\results\
echo ============================================
pause

endlocal
