#!/usr/bin/env bash
# Falcon 一键启动 (Mac)
# 后端 :8000 + 前端 :5173 同时启动；Ctrl+C 一并停止。

set -e
cd "$(dirname "$0")"

# 防御性清理：杀掉端口上的残留进程，再启动新的。
# 解决两类问题：
#   1. launchd / 后台残留的 Django/Vite 进程占用端口（典型表现：runserver --noreload
#      的僵尸跑着旧代码，热重载失效）
#   2. 上次 ./start.sh 异常退出没触发 cleanup
for port in 8000 5173 5174 5175; do
  pid=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "→ 清理端口 $port 残留进程 (pid $pid)"
    kill -9 $pid 2>/dev/null || true
  fi
done
sleep 0.3  # 给 OS 释放 socket 的时间，避免 bind: address already in use

# JMeter 跑起来需要 Java 17（Homebrew 装的 openjdk@17 是 keg-only）
export PATH="/opt/homebrew/opt/openjdk@17/bin:$PATH"

echo "→ 启动后端 (Django @ :8000) …"
( cd backend && ./venv/bin/python manage.py runserver ) &
BACKEND_PID=$!

echo "→ 启动前端 (Vite @ :5173) …"
( cd frontend && npm run dev ) &
FRONTEND_PID=$!

cleanup() {
  echo
  echo "→ 停止 …"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

cat <<EOF

  Backend  → http://localhost:8000   (pid $BACKEND_PID)
  Frontend → http://localhost:5173   (pid $FRONTEND_PID)

  Ctrl+C 同时停止两端
EOF

wait
