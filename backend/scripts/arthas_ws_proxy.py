#!/usr/bin/env python
"""Arthas Pod 终端 WebSocket 代理。

前端 xterm.js  ──ws──>  本代理(:8011)  ──wss──>  zapp-server Pod 终端

为什么要代理：浏览器原生 WebSocket ① 不能设 Authorization header ② 不能绕过系统代理；
而连 zapp-server 必须带 header + proxy=None（否则本机 Clash 代理会 reset 内网域名）。
故由本服务代连：本服务登录拿 JWT、带 header、proxy=None 连上游，再把字节双向桥接给前端。

跑（账号密码走环境变量，别写进代码/前端）：
  ZAPP_ACCOUNT=xxx ZAPP_PASSWORD=yyy ./venv/bin/python scripts/arthas_ws_proxy.py
前端连（Vite 代理 /arthas-term → :8011）：
  ws://localhost:5173/arthas-term?cluster=7&namespace=polymas&pod=<pod>&container=<容器>
"""
import asyncio
import os
import ssl
import sys
import time
from urllib.parse import parse_qs, urlparse

import requests
import websockets
from dotenv import load_dotenv

# 独立脚本，自己加载 backend/.env（拿 ZAPP_ACCOUNT / ZAPP_PASSWORD，不进 git）
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

HTTP = 'https://zapp-server.zhihuishu.com'
WS = 'wss://zapp-server.zhihuishu.com'
ACCOUNT = os.getenv('ZAPP_ACCOUNT', '')
PASSWORD = os.getenv('ZAPP_PASSWORD', '')
PORT = int(os.getenv('ARTHAS_PROXY_PORT', '8011'))

_tok = {'v': None, 'ts': 0.0}


def get_token() -> str:
    if _tok['v'] and time.time() - _tok['ts'] < 1500:  # 缓存 ~25 分钟
        return _tok['v']
    s = requests.Session()
    s.trust_env = False  # 绕代理
    r = s.post(f'{HTTP}/access/user/login', json={'account': ACCOUNT, 'password': PASSWORD}, timeout=10)
    d = r.json().get('data')
    tok = d if isinstance(d, str) else (d or {}).get('token')
    if not tok:
        raise RuntimeError(f'登录失败: {r.json()}')
    _tok.update(v=tok, ts=time.time())
    return tok


async def handler(client) -> None:
    q = parse_qs(urlparse(client.request.path).query)
    g = lambda k, dft='': (q.get(k, [dft])[0])
    cluster, ns, pod, container = g('cluster', '1'), g('namespace'), g('pod'), g('container')
    if not (ns and pod and container):
        await client.send('\r\n[代理] 缺少 namespace/pod/container 参数\r\n')
        await client.close(code=1008)
        return
    try:
        token = get_token()
    except Exception as e:  # noqa: BLE001
        await client.send(f'\r\n[代理] {e}\r\n')
        await client.close()
        return

    url = f'{WS}/ws/cluster/{cluster}/namespace/{ns}/pod/{pod}/container/{container}/terminal'
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    print(f'[proxy] 连上游 {url}', file=sys.stderr)
    try:
        async with websockets.connect(
            url, additional_headers={'Authorization': token}, ssl=ctx,
            proxy=None, open_timeout=15, ping_interval=20, max_size=None,
        ) as up:
            async def c2u():
                async for m in client:
                    await up.send(m)

            async def u2c():
                async for m in up:
                    await client.send(m)

            done, pending = await asyncio.wait(
                [asyncio.create_task(c2u()), asyncio.create_task(u2c())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except Exception as e:  # noqa: BLE001
        try:
            await client.send(f'\r\n[代理] 连接 Pod 失败: {type(e).__name__} {e}\r\n')
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    if not (ACCOUNT and PASSWORD):
        print('请先设 ZAPP_ACCOUNT / ZAPP_PASSWORD 环境变量', file=sys.stderr)
        sys.exit(1)
    print(f'[arthas-proxy] 监听 ws://localhost:{PORT}（Vite /arthas-term 转发到这里）', file=sys.stderr)
    async with websockets.serve(handler, 'localhost', PORT, max_size=None):
        await asyncio.Future()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
