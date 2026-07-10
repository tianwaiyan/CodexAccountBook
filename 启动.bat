@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Closing old Streamlit...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo Starting server (background)...
start "" /B pythonw -m streamlit run app.py --server.port 8501 --server.headless true

echo Waiting for server...
timeout /t 5 /nobreak >nul

echo Opening browser...
start "" http://localhost:8501
exit