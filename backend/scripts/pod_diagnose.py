#!/usr/bin/env python
"""Pod 只读诊断采集器（非交互、自动发送+读取，供分析 / 后续喂模型）。

连进 Pod 终端 → 跑一组**一次性、只读**的诊断命令（JDK 自带 jps/jstat/jstack/jmap，
不改任何东西）→ 抓输出 → 打印（可选 --save 存进 Falcon 的 RunArthasCapture 表）。

为什么用 JDK 一次性命令而不是 arthas 交互 REPL：一次性命令好自动化、输出有界、不需要
attach 暂停 JVM。需要方法级 trace 时再单独用 arthas 的 trace/watch。

用法：
  ./venv/bin/python scripts/pod_diagnose.py \
      --cluster 8 --namespace apps --pod app-2c-xxxx --container app-2c
  # 存进某个 run 的诊断库（供 Step4 / 模型）：再加  --save <run_id>
凭据走 backend/.env（ZAPP_ACCOUNT / ZAPP_PASSWORD）。
"""
import argparse
import asyncio
import os
import re
import ssl
import sys

import requests
import websockets
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

HTTP = 'https://zapp-server.zhihuishu.com'
WS = 'wss://zapp-server.zhihuishu.com'
ACCOUNT = os.getenv('ZAPP_ACCOUNT', '')
PASSWORD = os.getenv('ZAPP_PASSWORD', '')
FALCON_API = os.getenv('FALCON_API', 'http://localhost:8000/api/performance')

DONE = '__FALCON_DONE__'
# 只读诊断：找业务 PID（排除 jps/arthas 自身）→ GC 统计 / 线程 dump / 堆直方图。全是一次性命令。
DIAG_ONELINER = (
    "P=$(jps -l 2>/dev/null | grep -vE 'arthas-boot|sun.tools|jdk.jcmd|Jps' "
    "| head -1 | awk '{print $1}'); P=${P:-1}; "
    "echo \"##### PID=$P\"; "
    "echo '##### [jstat -gc] GC 各代/次数/耗时'; jstat -gc $P 2>&1; "
    "echo '##### [jstack] 线程栈(前150行)'; jstack $P 2>&1 | head -150; "
    "echo '##### [jmap -histo:live] 堆对象直方图(前40)'; jmap -histo:live $P 2>&1 | head -40; "
    f"echo {DONE}"
)


def login() -> str:
    s = requests.Session()
    s.trust_env = False
    d = s.post(f'{HTTP}/access/user/login', json={'account': ACCOUNT, 'password': PASSWORD}, timeout=10).json().get('data')
    tok = d if isinstance(d, str) else (d or {}).get('token')
    if not tok:
        raise SystemExit('登录失败')
    return tok


def _clean(s: str) -> str:
    return re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', s).replace('\r', '')


async def collect(cluster, namespace, pod, container) -> str:
    token = login()
    url = f'{WS}/ws/cluster/{cluster}/namespace/{namespace}/pod/{pod}/container/{container}/terminal'
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    print(f'[ws] 连接 {pod}/{container} …', file=sys.stderr)
    async with websockets.connect(url, additional_headers={'Authorization': token}, ssl=ctx,
                                  proxy=None, open_timeout=15, max_size=None) as ws:
        # 等 shell 就绪
        await asyncio.sleep(1.0)
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
        print('[ws] 已连接，发送只读诊断命令…', file=sys.stderr)
        await ws.send(DIAG_ONELINER + '\n')
        buf = ''
        deadline = asyncio.get_event_loop().time() + 60
        while asyncio.get_event_loop().time() < deadline:
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=max(0.2, deadline - asyncio.get_event_loop().time()))
            except asyncio.TimeoutError:
                break
            buf += m if isinstance(m, str) else m.decode('utf-8', 'ignore')
            if DONE in buf:
                break
        out = _clean(buf)
        # 去掉回显的命令行本身和结束标记
        out = out.split(DONE)[0]
        idx = out.find('##### PID=')
        return out[idx:] if idx >= 0 else out


def save(run_id: str, pod: str, output: str) -> None:
    r = requests.post(f'{FALCON_API}/runs/{run_id}/arthas-captures/',
                      json={'pod': pod, 'command': 'jvm 只读诊断(jstat/jstack/jmap)',
                            'output': output[:60000], 'note': '自动采集'}, timeout=10)
    print(f'[save] HTTP {r.status_code}', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cluster', required=True)
    ap.add_argument('--namespace', required=True)
    ap.add_argument('--pod', required=True)
    ap.add_argument('--container', required=True)
    ap.add_argument('--save', help='存进该 run_id 的诊断库')
    a = ap.parse_args()
    if not (ACCOUNT and PASSWORD):
        raise SystemExit('请在 backend/.env 配 ZAPP_ACCOUNT / ZAPP_PASSWORD')
    out = asyncio.run(collect(a.cluster, a.namespace, a.pod, a.container))
    print('\n' + '=' * 60 + '\n' + out + '\n' + '=' * 60)
    if a.save:
        save(a.save, a.pod, out)


if __name__ == '__main__':
    main()
