@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting...
start "" python -m streamlit run app.py --server.port 8501 --server.headless true
timeout /t 5 /nobreak >nul
start "" http://localhost:8501
echo http://localhost:8501
pause
