@echo off
cd /d "%~dp0frontend"
if not exist node_modules call npm install
echo Frontend starting at http://localhost:5173
npm run dev
