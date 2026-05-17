@echo off
chcp 65001 >nul
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo [LOI] Ung dung bi loi. Hay chay install.bat truoc.
    pause
)
