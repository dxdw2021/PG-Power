@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   PG-Power GPIB电源实时采集工具
echo ========================================
echo.
echo 正在启动图形界面...
start "" /D"%~dp0" "venv\Scripts\pythonw.exe" main.py
echo 程序已启动，请查看桌面窗口。
echo.
pause
