@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo   微信内容路由（Windows）  安装后首次配置向导
echo ============================================================
echo.
echo 本向导会先安装依赖，然后依次向你确认三件事：
echo   1. 链接存到哪里   （Obsidian 仓库 / 本地文件夹）
echo   2. 用哪个微信账号
echo   3. 从你的「文件传输助手」读取链接（或指定某个聊天）
echo.
echo [1/2] 安装 Python 依赖（首次较慢，请稍候）...
python -m pip install -r scripts\requirements.txt
if errorlevel 1 (
  echo.
  echo [错误] Python 依赖安装失败，请确认已安装 Python 3 并已加入 PATH。
  pause
  exit /b 1
)
echo.
echo [2/2] 启动配置向导...
python scripts\bootstrap_config.py
echo.
echo 配置已写入 scripts\config.json。
echo 以后在 WorkBuddy 召唤「微信内容路由（Windows）」专家即可直接使用。
echo 需要重配时，可再双击本文件，或召唤专家后选「重新配置」。
pause
endlocal
