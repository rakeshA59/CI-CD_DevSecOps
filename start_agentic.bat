@echo off
REM CIP agentic edition: API (FastAPI + LangGraph) on :8000, MCP servers on :8051/:8052, React app on :5173
setlocal
cd /d %~dp0cip-api

REM Pick a Python: the "py" launcher with 3.12 / 3.13 if present, else "python" on PATH.
set "PY=python"
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if "%PY%"=="python" py -3.13 -c "import sys" >nul 2>&1 && set "PY=py -3.13"
%PY% -c "import sys; print('Using Python', sys.version.split()[0], sys.executable)" || (echo No working Python found - install Python 3.12 from python.org & pause & exit /b 1)

REM A venv whose base Python was removed or moved fails this check, so it is rebuilt.
if exist .venv (.venv\Scripts\python -c "import sys" >nul 2>&1 || (echo Rebuilding broken .venv & rmdir /s /q .venv))
if not exist .venv (%PY% -m venv .venv && .venv\Scripts\python -m pip install --upgrade pip && .venv\Scripts\pip install -r requirements.txt)

REM Security scanners go into .scanners (own venv + downloaded binaries), never into .venv. Installed once;
REM rerun "scripts\install_scanners.py" any time to update them.
if exist .scanners\Scripts (.scanners\Scripts\python -c "import sys" >nul 2>&1 || rmdir /s /q .scanners)
if not exist .scanners\installed.txt (.venv\Scripts\python scripts\install_scanners.py && echo done> .scanners\installed.txt)

if not exist .env copy .env.example .env
start "CIP scanner MCP" cmd /k .venv\Scripts\python -m mcp_services.mcp_servers.scanner_mcp.server
start "CIP docker MCP"  cmd /k .venv\Scripts\python -m mcp_services.mcp_servers.docker_mcp.server
start "CIP API" cmd /k .venv\Scripts\python -m uvicorn main:app --port 8000
cd /d %~dp0cip-app
if not exist node_modules call npm install
start "CIP app" cmd /k npm run dev
timeout /t 6 >nul
start http://localhost:5173
