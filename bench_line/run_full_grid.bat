@echo off
REM ============================================================================
REM MABDT Engine - Unified Line-Mode Grid
REM ============================================================================
REM The single experiment that subsumes the old bench/ sensitivity grid AND
REM adds the assembly-line metrics (takt, lead time, WIP).
REM
REM Part 1 - staggered arrivals, the old (N x r) grid:
REM   N in {15, 50, 150, 500, 1000} x r in {30, 100, 300, 1000, 3000, 10000}
REM   T = 2N/r per cell, ~60 s observation windows (at least 5 cycles).
REM Part 2 - burst sensitivity, one rate per N (r=1000, synchronized worst case).
REM Part 3 (optional) - deployment-realistic showcase: N=15 at the lab's real
REM   60 s takt, 40 cycles (~45 min), full lead-time coverage.
REM
REM Environment toggles (set before launching):
REM   set REPS=3           repeat the whole grid 3x (rows tagged rep1..rep3,
REM                        per-run files suffixed _rep1.. so nothing collides)
REM   set RUN_SHOWCASE=1   append the Part 3 showcase run
REM   set NOPAUSE=1        no pause prompts (for unattended/overnight runs)
REM
REM One pass is ~60-90 minutes. NOTE: launching this script deletes the
REM previous summary.csv; per-run CSVs are only overwritten when the same
REM (N, T, arrival, tag) combination is rerun.
REM
REM Prerequisites: .venv ready (pip install -e ".[tiger]" plus psutil,
REM matplotlib), MQTT broker on 127.0.0.1:8883.
REM
REM Output:
REM   bench_line\results\summary.csv                          (one row per run)
REM   bench_line\results\N{N}_T{T}_{arrival}[_tag]_latency.csv
REM   bench_line\results\N{N}_T{T}_{arrival}[_tag]_resources.csv
REM   bench_line\results\N{N}_T{T}_{arrival}[_tag]_engine.log
REM   bench_line\results\line_latency.png / line_saturation.png /
REM                      line_takt.png / line_lead.png
REM ============================================================================

setlocal enabledelayedexpansion

cd /d "%~dp0.."

if not defined REPS set REPS=1

echo.
echo ============================================
echo MABDT Engine - Unified Line-Mode Grid  (repetitions: %REPS%)
echo ============================================
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at .venv
    echo Create it with:  python -m venv .venv
    echo Then install:    pip install -e ".[tiger]"
    if not defined NOPAUSE pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo [INFO] Checking MQTT broker reachability at 127.0.0.1:8883...
python bench_line\check_broker.py --host 127.0.0.1 --port 8883
if errorlevel 1 (
    echo.
    echo [ERROR] MQTT broker not reachable.
    echo Start Mosquitto ^(or your broker^) on 127.0.0.1:8883 and retry.
    call deactivate
    if not defined NOPAUSE pause
    exit /b 1
)
echo [OK] Broker reachable.
echo.

if exist "bench_line\results\summary.csv" (
    echo [INFO] Removing previous bench_line\results\summary.csv
    del /q "bench_line\results\summary.csv"
)
echo.

set /a TOTAL=35*%REPS%
set /a DONE=0

for /L %%K in (1,1,%REPS%) do (
    echo ============================================
    echo Repetition %%K of %REPS% - Part 1: staggered arrivals, full N x rate grid
    echo ============================================

    for %%N in (15 50 150 500 1000) do (
        for %%R in (30 100 300 1000 3000 10000) do (
            set /a DONE+=1
            echo ============================================
            echo [!DONE!/%TOTAL%] N=%%N rate=%%R eps, staggered, rep%%K
            echo ============================================
            python -m bench_line.benchmark --N %%N --rate %%R --duration 60 --arrival staggered --tag rep%%K
            if errorlevel 1 (
                echo [ERROR] Benchmark failed at N=%%N rate=%%R staggered rep%%K
                call deactivate
                if not defined NOPAUSE pause
                exit /b 1
            )
            echo.
        )
    )

    echo ============================================
    echo Repetition %%K of %REPS% - Part 2: burst sensitivity at r=1000
    echo ============================================

    for %%N in (15 50 150 500 1000) do (
        set /a DONE+=1
        echo ============================================
        echo [!DONE!/%TOTAL%] N=%%N rate=1000 eps, burst, rep%%K
        echo ============================================
        python -m bench_line.benchmark --N %%N --rate 1000 --duration 60 --arrival burst --tag rep%%K
        if errorlevel 1 (
            echo [ERROR] Benchmark failed at N=%%N rate=1000 burst rep%%K
            call deactivate
            if not defined NOPAUSE pause
            exit /b 1
        )
        echo.
    )
)

if defined RUN_SHOWCASE (
    echo ============================================
    echo Part 3: deployment-realistic showcase - N=15, T=60 s, 40 cycles ^(~45 min^)
    echo ============================================
    python -m bench_line.benchmark --N 15 --cycle-time 60 --cycles 40 --tag showcase
    if errorlevel 1 (
        echo [ERROR] Showcase run failed
    )
    echo.
)

echo ============================================
echo Verifying and aggregating results
echo ============================================
python -m bench_line.verify_summary
echo.
python -m bench_line.analyze
echo.

call deactivate

echo.
echo ============================================
echo Unified grid complete.
echo Results: bench_line\results\
echo ============================================
if not defined NOPAUSE pause

endlocal
