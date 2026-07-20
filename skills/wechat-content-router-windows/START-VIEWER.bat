@echo off
cd /d "%~dp0scripts"

where node >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Node.js，请先安装: https://nodejs.org
    pause
    exit /b 1
)

REM 检查/安装 koffi（首次运行）
if not exist "node_modules\koffi" (
    echo [首次运行] 正在安装依赖 (koffi)...
    call npm install koffi 2>nul
)

echo.
echo ========================================
echo   微信只读查看器 (Windows)
echo ========================================
echo   地址: http://127.0.0.1:8731
echo ---------------------------------------
start http://127.0.0.1:8731
node viewer-server.mjs
pause
