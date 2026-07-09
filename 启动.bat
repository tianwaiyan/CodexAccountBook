@echo off
chcp 65001 >nul
cd /d "%~dp0"
start /B python -m streamlit run app.py --server.port 8501 --server.headless true
timeout /t 5 /nobreak >nul
start "" http://localhost:8501
exit
