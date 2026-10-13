@echo off
REM Starts all three EntryGuard processes plus an ngrok tunnel that publishes
REM the API on a constant public URL, each in its own window.
REM Run this from anywhere - it cd's to its own folder first.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Could not find venv\Scripts\python.exe - create the venv and install requirements.txt first.
    pause
    exit /b 1
)

REM NGROK_DOMAIN in .env is the reserved ngrok domain the API is published on
REM (e.g. NGROK_DOMAIN=https://entryguard.ngrok-free.app). A *reserved* domain
REM is what keeps the public URL constant across restarts - without one ngrok
REM hands out a fresh random URL every time.
set "NGROK_DOMAIN="
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        if /i "%%A"=="NGROK_DOMAIN" set "NGROK_DOMAIN=%%B"
    )
)

REM --host 0.0.0.0 so Swagger is reachable from other machines on the LAN
REM at http://<this-pc-ip>:8000/docs, not just localhost. Port 8501 is
REM Streamlit's UI - the API and its docs are always on 8000.
start "EntryGuard - API"      cmd /k "venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"
start "EntryGuard - Worker"   cmd /k "venv\Scripts\celery -A backend.celery_app worker --loglevel=info --pool=solo"
start "EntryGuard - Frontend" cmd /k "venv\Scripts\streamlit run frontend/app.py"

where ngrok >nul 2>nul
if errorlevel 1 (
    echo.
    echo ngrok not found on PATH - the API is only reachable on localhost:8000.
    echo   1. winget install ngrok.ngrok
    echo   2. ngrok config add-authtoken ^<your token^>
    echo   3. claim a free domain at https://dashboard.ngrok.com/domains
    echo   4. set NGROK_DOMAIN in .env to it, then re-run this script.
    goto :done
)

if defined NGROK_DOMAIN (
    start "EntryGuard - ngrok" cmd /k "ngrok http 8000 --url=%NGROK_DOMAIN%"
    echo API published at %NGROK_DOMAIN%
) else (
    echo.
    echo NGROK_DOMAIN is not set in .env - starting ngrok with a random URL that
    echo changes on every restart. Claim a free reserved domain at
    echo https://dashboard.ngrok.com/domains and set NGROK_DOMAIN to keep it constant.
    start "EntryGuard - ngrok" cmd /k "ngrok http 8000"
)

:done
