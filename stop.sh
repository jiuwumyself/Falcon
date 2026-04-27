#!/usr/bin/env bash
# Falcon 一键停止 (Mac) — 按端口杀两端。
# 适用于 start.sh 异常退出后还有遗留进程占着端口的情况。

for port in 8000 5173 5174 5175; do
  pid=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "[kill] port=$port pid=$pid"
    kill -9 $pid 2>/dev/null || true
  else
    echo "[skip] port=$port not listening"
  fi
done
echo "[ok] done"
