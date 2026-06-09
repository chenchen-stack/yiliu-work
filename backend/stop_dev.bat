@echo off
echo Stopping listeners on port 8000 ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:8000" ^| findstr LISTENING') do (
  echo taskkill PID %%a
  taskkill /F /PID %%a >nul 2>&1
)
echo Done. If port still busy, end all "python.exe" in Task Manager.
