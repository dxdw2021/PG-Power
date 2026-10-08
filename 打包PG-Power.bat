@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   PG-Power 打包工具 (PyInstaller)
echo ========================================
echo.

REM 清理旧的打包文件
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo [1/3] 正在打包，请等待（约1-3分钟）...
echo.

REM 使用 spec 文件打包（onedir 模式，启动更快）
venv\Scripts\pyinstaller pg-power.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！
    pause
    exit /b 1
)

echo.
echo [2/3] 打包完成！
echo.

echo [3/3] 输出: %~dp0dist\PG-Power.exe
echo.
echo ========================================
echo   打包成功！
echo.
echo   单文件版: dist\PG-Power.exe (66MB)
echo   复制到目标电脑即可运行。
echo ========================================
pause
