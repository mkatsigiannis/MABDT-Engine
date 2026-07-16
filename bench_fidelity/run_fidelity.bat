@echo off
REM ============================================================================
REM MABDT Engine - Stochastic-Line Fidelity Study
REM ============================================================================
REM Runs the digital twin against a seeded stochastic simulation of the
REM Tiger Motors line (takt 75 s, Triangular(50,60,70) s service,
REM Uniform(1,3) s grab delays, 100x time compression, 120 cars) and
REM compares the DT's observations against the generator's ground truth.
REM
REM Scenarios:
REM   balanced   x seeds {1,2,3}   - all stations share the same distribution
REM   bottleneck x seeds {1,2,3}   - WS8 scaled by 1.2 (utilization ~0.96):
REM                                  queue upstream, starvation downstream;
REM                                  the DT should localize the constraint.
REM
REM 6 runs x ~2.5 min  =  ~15-20 minutes total.
REM   set NOPAUSE=1   for unattended runs.
REM
REM Output:
REM   bench_fidelity\results\summary.csv           (one row per run)
REM   bench_fidelity\results\{tag}_truth.csv        (ground-truth schedule)
REM   bench_fidelity\results\{tag}_latency.csv      (per-event DT timings)
REM   bench_fidelity\results\{tag}_leads.csv        (paired per-car lead times)
REM   bench_fidelity\results\{tag}_utilization.csv  (per-station busy times)
REM   bench_fidelity\results\{tag}_lead_ecdf.png    (truth-vs-DT ECDF overlay)
REM   bench_fidelity\results\{tag}_utilization.png  (per-station bars)
REM ============================================================================

setlocal enabledelayedexpansion

cd /d "%~dp0.."

echo.
echo ============================================
echo MABDT Engine - Stochastic-Line Fidelity Study
echo ============================================
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at .venv
    if not defined NOPAUSE pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo [INFO] Checking MQTT broker reachability at 127.0.0.1:8883...
python bench_fidelity\check_broker.py --host 127.0.0.1 --port 8883
if errorlevel 1 (
    echo [ERROR] MQTT broker not reachable.
    call deactivate
    if not defined NOPAUSE pause
    exit /b 1
)
echo [OK] Broker reachable.
echo.

if exist "bench_fidelity\results\summary.csv" (
    echo [INFO] Removing previous bench_fidelity\results\summary.csv
    del /q "bench_fidelity\results\summary.csv"
)
echo.

set /a TOTAL=6
set /a DONE=0

for %%S in (1 2 3) do (
    set /a DONE+=1
    echo ============================================
    echo [!DONE!/%TOTAL%] balanced line, seed %%S
    echo ============================================
    python -m bench_fidelity.benchmark --cars 120 --compression 100 --seed %%S
    if errorlevel 1 (
        echo [ERROR] Fidelity run failed: balanced seed %%S
        call deactivate
        if not defined NOPAUSE pause
        exit /b 1
    )
    echo.
)

for %%S in (1 2 3) do (
    set /a DONE+=1
    echo ============================================
    echo [!DONE!/%TOTAL%] bottleneck at WS8 ^(x1.2^), seed %%S
    echo ============================================
    python -m bench_fidelity.benchmark --cars 120 --compression 100 --seed %%S --bottleneck-station 8
    if errorlevel 1 (
        echo [ERROR] Fidelity run failed: bottleneck seed %%S
        call deactivate
        if not defined NOPAUSE pause
        exit /b 1
    )
    echo.
)

echo ============================================
echo Aggregating results
echo ============================================
python -m bench_fidelity.analyze
echo.

call deactivate

echo.
echo ============================================
echo Fidelity study complete.
echo Results: bench_fidelity\results\
echo ============================================
if not defined NOPAUSE pause

endlocal
