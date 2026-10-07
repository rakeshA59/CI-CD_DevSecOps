@echo off
REM DevOps agentic edition: API (FastAPI + LangGraph) on :8000, MCP servers on :8051/:8052 (started by the API), React app on :5173
setlocal
cd /d %~dp0cip-api

REM Pick a Python: the "py" launcher with 3.12 / 3.13 if present, else "python" on PATH.
set "PY=python"
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if "%PY%"=="python" py -3.13 -c "import sys" >nul 2>&1 && set "PY=py -3.13"
%PY% -c "import sys; print('Using Python', sys.version.split()[0], sys.executable)" || (echo No working Python found - install Python 3.12 from python.org & pause & exit /b 1)

REM The API's venv: an existing "venv" folder is used as it is, else ".venv" (created on first start).
REM A venv whose base Python was removed or moved fails this check, so it is rebuilt.
set "VENV=.venv"
if exist venv\Scripts\python.exe set "VENV=venv"
if exist %VENV% (%VENV%\Scripts\python -c "import sys" >nul 2>&1 || (echo Rebuilding broken %VENV% & rmdir /s /q %VENV%))
if not exist %VENV% (%PY% -m venv %VENV% && %VENV%\Scripts\python -m pip install --upgrade pip && %VENV%\Scripts\pip install -r requirements.txt)

REM Security scanners go into .scanners (own venv + downloaded binaries), never into the API's venv. Installed once;
REM rerun "scripts\install_scanners.py" any time to update them (the pipeline also installs / repairs them itself).
if exist .scanners\Scripts (.scanners\Scripts\python -c "import sys" >nul 2>&1 || rmdir /s /q .scanners)
if not exist .scanners\installed.txt (%VENV%\Scripts\python scripts\install_scanners.py && echo done> .scanners\installed.txt)

if not exist .env copy .env.example .env
REM The API starts the scanner (:8051) and docker (:8052) MCP servers itself.
start "DevOps API" cmd /k %VENV%\Scripts\python -m uvicorn main:app --port 8000
cd /d %~dp0cip-app
if not exist node_modules call npm install
start "DevOps app" cmd /k npm run dev
timeout /t 6 >nul
start http://localhost:5173
