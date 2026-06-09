@echo off
cd /d "%~dp0"

echo === 停止占用 8000/5173 端口的旧进程 ===
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173.*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak >nul

echo === 启动 MVP 后端 (0.2.0-mvp) ===
start "yiliu-backend" cmd /k "cd /d %~dp0backend && call .venv\Scripts\activate.bat && uvicorn app.main:app --reload --port 8000"

timeout /t 3 /nobreak >nul

echo === 启动前端 ===
start "yiliu-frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 4 /nobreak >nul
start http://localhost:5173/login

echo.
echo 已启动。请使用 admin/admin123 登录，先在管理后台确认业务中心已发布。
echo 后端文档: http://127.0.0.1:8000/docs
pause
