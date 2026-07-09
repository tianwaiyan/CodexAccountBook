@echo off
cd /d "%~dp0"
echo Starting Bill Merger...
powershell -WindowStyle Hidden -Command "Start-Process python -ArgumentList '-m','streamlit','run','app.py','--server.port','8501','--server.headless','true' -WindowStyle Hidden"
timeout /t 5 /nobreak >nul
start "" http://localhost:8501
echo Opened http://localhost:8501
exit
