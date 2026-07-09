@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] Closing old Streamlit...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [2/3] Starting server...
start /B python -m streamlit run app.py --server.port 8501 --server.headless true

echo [3/3] Opening browser...
timeout /t 5 /nobreak >nul
start "" http://localhost:8501
echo Done! Press any key to exit...
pause >nul
exit
