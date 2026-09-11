#!/usr/bin/env python
"""Arthas Pod 终端 WebSocket 代理。

前端 xterm.js  ──ws──>  本代理(:8011)  ──wss──>  zapp-server Pod 终端

为什么要代理：浏览器原生 WebSocket ① 不能设 Authorization header ② 不能绕过系统代理；
而连 zapp-server 必须带 header + proxy=None（否则本机 Clash 代理会 reset 内网域名）。
故由本服务代连：本服务登录拿 JWT、带 header、proxy=None 连上游，再把字节双向桥接给前端。

跑（账号密码走环境变量，别写进代码/前端）：
  ./venv/bin/python scripts/arthas_ws_proxy.py
（账号密码优先读 admin 的「Arthas 全局配置」，留空时回落 ZAPP_ACCOUNT / ZAPP_PASSWORD）
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

_DEFAULT_HTTP = 'https://zapp-server.zhihuishu.com'
_DEFAULT_WS = 'wss://zapp-server.zhihuishu.com'
PORT = int(os.getenv('ARTHAS_PROXY_PORT', '8011'))

# 配置优先读 ArthasConfig 单例表（admin 里改、无需重启本进程），库里留空回落环境变量。
# 本进程是 sidecar / 独立脚本，这里自己起一次 Django ORM。
_CFG_TTL = 30.0          # 缓存 30s：既不每次连接都查库，也能让 admin 改动很快生效
_cfg_cache = {'v': None, 'ts': 0.0}
_django_ready = False


def _ensure_django() -> bool:
    global _django_ready
    if _django_ready:
        return True
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
        import django  # noqa: PLC0415
        django.setup()
        _django_ready = True
    except Exception as e:  # noqa: BLE001
        print(f'[arthas-proxy] Django 初始化失败，回落环境变量: {e}', file=sys.stderr, flush=True)
    return _django_ready


def _cfg() -> dict:
    now = time.time()
    if _cfg_cache['v'] is not None and now - _cfg_cache['ts'] < _CFG_TTL:
        return _cfg_cache['v']
    http_url = ws_url = account = password = ''
    enabled = True
    if _ensure_django():
        try:
            from performance.models import ArthasConfig  # noqa: PLC0415
            c = ArthasConfig.get_config()
            enabled = c.enabled
            http_url = (c.http_base_url or '').strip()
            ws_url = (c.ws_base_url or '').strip()
            account = (c.account or '').strip()
            password = c.password or ''
        except Exception as e:  # noqa: BLE001
            print(f'[arthas-proxy] 读 ArthasConfig 失败，回落环境变量: {e}',
                  file=sys.stderr, flush=True)
    out = {
        'enabled': enabled,
        'http': http_url or os.getenv('ZAPP_BASE_URL', _DEFAULT_HTTP),
        'ws': ws_url or _DEFAULT_WS,
        'account': account or os.getenv('ZAPP_ACCOUNT', ''),
        'password': password or os.getenv('ZAPP_PASSWORD', ''),
    }
    _cfg_cache.update(v=out, ts=now)
    return out

_tok = {'v': None, 'ts': 0.0}


def get_token() -> str:
    if _tok['v'] and time.time() - _tok['ts'] < 1500:  # 缓存 ~25 分钟
        return _tok['v']
    s = requests.Session()
    s.trust_env = False  # 绕代理
    c = _cfg()
    r = s.post(f'{c["http"]}/access/user/login',
               json={'account': c['account'], 'password': c['password']}, timeout=10)
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

    url = (f'{_cfg()["ws"]}/ws/cluster/{cluster}/namespace/{ns}'
           f'/pod/{pod}/container/{container}/terminal')
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
    c = _cfg()
    if not (c['account'] and c['password']):
        print('未配置 Arthas 账号密码：请在 admin 的「Arthas 全局配置」里填写，'
              '或设环境变量 ZAPP_ACCOUNT / ZAPP_PASSWORD', file=sys.stderr)
        sys.exit(1)
    print(f'[arthas-proxy] 监听 ws://localhost:{PORT}（Vite /arthas-term 转发到这里）', file=sys.stderr)
    async with websockets.serve(handler, 'localhost', PORT, max_size=None):
        await asyncio.Future()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
