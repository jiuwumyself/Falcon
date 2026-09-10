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

# Arthas Pod 终端 WS 代理（:8011）：前端 /arthas-term → 这里 → zapp-server pod 终端。
# 不起它，前端 Arthas 终端会「连接中…连接已关闭」。凭据走 backend/.env 的 ZAPP_*。
echo "→ 启动 Arthas WS 代理 (@ :8011) …"
( cd backend && ./venv/bin/python scripts/arthas_ws_proxy.py ) \
  >> /tmp/falcon-arthas-proxy.log 2>&1 &
ARTHAS_PID=$!

# 压力机已改为固定编制（生产 10 台常驻 agent），不再做自动回收：
# release_idle_agents 会把 30 分钟没心跳的 idle agent 标成 lost 并尝试销毁容器，
# 固定机器场景下有害无益（网络抖动一次就可能把好机器摘掉）。
# 真要用回动态编制，把下面这段恢复，并把 settings 的 SCALING_ENABLED 设成 true。
RELEASE_PID=""

# 定时任务 tick：每分钟扫到点的 TaskSchedule，HTTP 触发 web 的 run 接口起压测。
# 生产环境走 K8s CronJob（deploy/k8s/80-scheduler-cronjob.yaml）。
echo "→ 启动定时任务调度 (每 1 min run_due_schedules) …"
(
  while true; do
    sleep 60
    ( cd backend && ./venv/bin/python manage.py run_due_schedules ) \
      >> /tmp/falcon-schedules.log 2>&1 || true
  done
) &
SCHEDULE_PID=$!

cleanup() {
  echo
  echo "→ 停止 …"
  kill "$BACKEND_PID" "$FRONTEND_PID" "$ARTHAS_PID" "$SCHEDULE_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

cat <<EOF

  Backend         → http://localhost:8000   (pid $BACKEND_PID)
  Frontend        → http://localhost:5173   (pid $FRONTEND_PID)

  Ctrl+C 同时停止
EOF

wait
