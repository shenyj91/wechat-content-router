#!/bin/bash
cd "$(dirname "$0")/scripts"

# 优先使用系统 node
if ! command -v node >/dev/null 2>&1; then
  osascript -e 'display alert "未找到 Node.js" message "请先安装 Node.js：https://nodejs.org"'
  exit 1
fi

# 确保 koffi 已安装（向上查找 scripts / 上层 node_modules）
if [ ! -d node_modules/koffi ] && [ ! -d ../node_modules/koffi ]; then
  echo "首次运行：安装 koffi ..."
  npm install koffi --no-audit --no-fund 2>&1 | tail -3
fi

echo "启动微信只读查看器 ..."
node viewer-server.mjs &
SERVER_PID=$!
sleep 2
open http://127.0.0.1:8731
wait $SERVER_PID
