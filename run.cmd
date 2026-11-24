@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
python -m novel_audio %*
if errorlevel 1 pause
