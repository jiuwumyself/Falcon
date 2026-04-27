#!/usr/bin/env bash
# Falcon 一键启动 (Mac)
# 后端 :8000 + 前端 :5173 同时启动；Ctrl+C 一并停止。

set -e
cd "$(dirname "$0")"

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
