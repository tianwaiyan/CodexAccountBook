@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" http://localhost:8501
python -m streamlit run app.py --server.port 8501 --server.headless true
pause
