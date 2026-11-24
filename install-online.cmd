@echo off
setlocal
cd /d "%~dp0"
set "NOVEL_ENV=assets\.venv"
if not exist "%NOVEL_ENV%\Scripts\python.exe" (
    python -m venv "%NOVEL_ENV%"
    if errorlevel 1 goto failed
)
"%NOVEL_ENV%\Scripts\python.exe" -m pip install --no-cache-dir -r requirements-online.txt
if errorlevel 1 goto failed
echo Online voices installed. Restart run.cmd to use them.
pause
exit /b 0
:failed
echo Installation failed. Check Python 3.11+ and network access.
pause
exit /b 1
