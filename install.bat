@echo off
chcp 65001 >nul
echo ============================================
echo   Cai dat Video Dich Thuat Tieng Viet
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Python chua duoc cai dat!
    echo Tai Python tai: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python da duoc cai dat.

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [CANH BAO] FFmpeg chua duoc cai dat.
    echo Chay lenh nay de cai FFmpeg: winget install ffmpeg
    echo Hoac tai tai: https://ffmpeg.org/download.html
    echo.
    echo Ban co the tiep tuc cai dat Python packages...
) else (
    echo [OK] FFmpeg da duoc cai dat.
)

echo.
echo Dang cai dat cac thu vien Python...
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [LOI] Co loi khi cai dat. Hay kiem tra ket noi mang.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Cai dat hoan tat!
echo   Chay ung dung bang lenh: python main.py
echo   Hoac nhan doi vao run.bat
echo ============================================
pause
