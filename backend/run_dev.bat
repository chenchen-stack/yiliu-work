@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先创建虚拟环境: python -m venv .venv
  exit /b 1
)
echo Stopping old listeners on port 8000 ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:8000" ^| findstr LISTENING') do (
  taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul
echo Starting uvicorn on http://127.0.0.1:8000 ...
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
