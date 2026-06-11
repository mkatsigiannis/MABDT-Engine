@echo off
REM ============================================================================
REM Tiger Motors Digital Twin - LLM Service Launcher
REM ============================================================================
REM Starts the standalone LLM service that bridges Ollama and the digital
REM twin over MQTT. The service runs as a separate process per JIM §3.4
REM C52 and can be stopped, restarted, or replaced with a different model
REM without touching the rest of the engine.
REM
REM Prerequisites:
REM   - .venv created (python -m venv .venv) with the [llm] or [tiger]
REM     extras installed: pip install -e ".[tiger]"
REM   - Ollama installed and running locally (https://ollama.com)
REM   - MQTT broker reachable from this machine
REM
REM Any arguments passed to this script are forwarded to the service:
REM   run_llm_service.bat --model qwen3:4b --mqtt-host your-broker-host
REM   run_llm_service.bat --help
REM ============================================================================

echo ============================================
echo Tiger Motors LLM Service
echo ============================================
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo [WARNING] Virtual environment not found at .venv
    echo Please run: python -m venv .venv
    echo Then install requirements: pip install -e ".[tiger]"
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Set PYTHONPATH to include the project root
set PYTHONPATH=%~dp0

echo [INFO] Starting LLM service...
echo [INFO] Press Ctrl+C to stop the service
echo.

REM Run the LLM service as a module so the absolute imports resolve
python -m tiger_motors_dt.llm_service.tiger_llm_service %*

REM Deactivate virtual environment
deactivate

echo.
echo [INFO] LLM service stopped
pause
