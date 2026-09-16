@echo off
cd /d "%~dp0"
echo Starting ML API with Python 3.12 venv (PaddleOCR)...
".venv\Scripts\python.exe" api_server.py
