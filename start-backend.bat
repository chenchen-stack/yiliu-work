@echo off
cd /d "%~dp0backend"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q
echo Backend starting at http://127.0.0.1:8000
uvicorn app.main:app --reload --port 8000
