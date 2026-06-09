#!/usr/bin/env python
"""Arthas Pod 终端 —— 最小可跑原型。

链路验证：登录 zapp-server 拿 JWT → WebSocket 开进某个 K8s Pod 的终端(PTY) →
交互式 shell。跑通后即可在终端里启动 Arthas attach 本 Pod 的 JVM。

为什么用后端 Python 而不是浏览器先试：
- Python WS 客户端能自定义 Authorization Header（浏览器原生 WebSocket 不行）；
- 内网域名走系统代理会 502，这里 requests/websockets 都强制不走代理（trust_env=False / 不传 proxy）。

用法：
  ./venv/bin/python scripts/arthas_pod_terminal.py \
      --account <账号> --password <密码> \
      --pod bd-search-server-6b58cc55ff-knspr [--cluster 1] [--namespace apps]
  # 已有 token 时跳过登录：
  ./venv/bin/python scripts/arthas_pod_terminal.py --token <JWT> --pod <pod>
  # 只想验证登录拿 token，不开终端：
  ./venv/bin/python scripts/arthas_pod_terminal.py --account x --password y --login-only

连上后试：ls / java -version / ps -ef | grep java，再跑 arthas（as.sh 或 arthas-boot.jar）。
Ctrl+C 退出。
"""
import argparse
import asyncio
import ssl
import sys

import requests
import websockets

# 实测：登录 http/https 都通；WS 必须走 wss://（TLS/443），ws:// 明文不是合法 WS 端点。
BASE_HTTP = 'https://zapp-server.zhihuishu.com'
BASE_WS = 'wss://zapp-server.zhihuishu.com'


def _direct_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 绕系统代理（内网域名走代理会 502，同 Pinpoint 客户端）
    return s


def login(account: str, password: str) -> str:
    """POST /access/user/login {account,password} → JWT。"""
    r = _direct_session().post(
        f'{BASE_HTTP}/access/user/login',
        json={'account': account, 'password': password},
        timeout=10,
    )
    print(f'[login] HTTP {r.status_code}', file=sys.stderr)
    r.raise_for_status()
    d = r.json()
    # 业务 envelope：{code, message, data}。token 在 data 里；data 可能是 token 字符串本身。
    data = d.get('data') if isinstance(d, dict) else None

    def _find_token(obj):
        if isinstance(obj, str) and obj.count('.') == 2:   # 看着像 JWT
            return obj
        if not isinstance(obj, dict):
            return None
        for k in ('token', 'access_token', 'accessToken', 'jwt', 'Authorization'):
            if obj.get(k):
                return obj[k]
        return None

    token = _find_token(data) or _find_token(d)
    if not token:
        raise SystemExit(f'[login] 失败：code={d.get("code")} message={d.get("message")}（完整：{d}）')
    return token


async def open_terminal(token: str, cluster: str, namespace: str, pod: str,
                        container: str, bearer: bool) -> None:
    url = (f'{BASE_WS}/ws/cluster/{cluster}/namespace/{namespace}'
           f'/pod/{pod}/container/{container}/terminal')
    auth = f'Bearer {token}' if bearer else token
    sslctx = ssl.create_default_context()
    sslctx.check_hostname = False
    sslctx.verify_mode = ssl.CERT_NONE   # 内网证书，不校验
    print(f'[ws] 连接 {url}', file=sys.stderr)
    try:
        async with websockets.connect(
            url,
            additional_headers={'Authorization': auth},
            ssl=sslctx,
            proxy=None,                  # 关键：绕过系统代理（Clash 会 reset 内网域名）
            open_timeout=15,
            ping_interval=20,
            max_size=None,
        ) as ws:
            print('[ws] 已连接。下面进入 Pod 终端（Ctrl+C 退出）。'
                  '先试 `ls` / `java -version`，再跑 arthas。', file=sys.stderr)
            loop = asyncio.get_event_loop()

            async def reader():
                async for msg in ws:
                    if isinstance(msg, (bytes, bytearray)):
                        sys.stdout.buffer.write(msg)
                        sys.stdout.buffer.flush()
                    else:
                        sys.stdout.write(msg)
                        sys.stdout.flush()

            async def writer():
                while True:
                    line = await loop.run_in_executor(None, sys.stdin.readline)
                    if not line:
                        break
                    await ws.send(line)   # 先试原始透传；若网关要 JSON 帧再按返回内容调整

            await asyncio.gather(reader(), writer())
    except websockets.InvalidStatus as e:
        print(f'[ws] 握手被拒：{e}（多半是鉴权方式不对——'
              f'试 --bearer，或 token 要走 query 参数，需问研发）', file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f'[ws] 连接失败：{type(e).__name__}: {e}', file=sys.stderr)


async def diagnose(token: str, cluster: str, namespace: str, pod: str) -> None:
    """一次性试多种鉴权方式，找出能连上的那种（握手探测，不跑命令）。"""
    base = f'{BASE_WS}/k8s/cluster/{cluster}/namespace/{namespace}/pod/{pod}/terminal'
    origin = 'https://zapp-server.zhihuishu.com'
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    asyncio.get_event_loop().set_exception_handler(lambda *_: None)  # 压掉 websockets 清理噪声

    attempts = [
        ('header Authorization', base, {'additional_headers': {'Authorization': token}}),
        ('header Bearer', base, {'additional_headers': {'Authorization': f'Bearer {token}'}}),
        ('header token', base, {'additional_headers': {'token': token}}),
        ('header + Origin', base, {'additional_headers': {'Authorization': token, 'Origin': origin}}),
        ('cookie Authorization', base, {'additional_headers': {'Cookie': f'Authorization={token}'}}),
        ('cookie token', base, {'additional_headers': {'Cookie': f'token={token}'}}),
        ('query token', f'{base}?token={token}', {}),
        ('query Authorization', f'{base}?Authorization={token}', {}),
        ('subprotocol', base, {'subprotocols': [token]}),
    ]
    for name, url, kw in attempts:
        try:
            async with websockets.connect(url, ssl=ctx, open_timeout=10, max_size=None, **kw) as ws:
                print(f'[OK ✅] 「{name}」连上了！', file=sys.stderr)
                try:
                    m = await asyncio.wait_for(ws.recv(), timeout=3)
                    print(f'        首屏: {repr(m)[:160]}', file=sys.stderr)
                except asyncio.TimeoutError:
                    print('        (连上但 3s 无首屏数据)', file=sys.stderr)
                return
        except Exception as e:  # noqa: BLE001
            msg = f'{type(e).__name__}: {str(e)[:70]}'
            print(f'[xx] 「{name}」-> {msg}', file=sys.stderr)
        await asyncio.sleep(0.3)
    print('[done] 以上方式都没连上——需问研发 WS 具体怎么鉴权 / 是否要 Origin / 是不是走 127.0.0.1:8000 那个本地网关', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--account')
    ap.add_argument('--password')
    ap.add_argument('--token', help='直接给 JWT，跳过登录')
    ap.add_argument('--pod')
    ap.add_argument('--container', help='容器名（如 polymas-user / app-2c）；缺省取 pod 名去掉副本后缀')
    ap.add_argument('--cluster', default='1')
    ap.add_argument('--namespace', default='apps')
    ap.add_argument('--bearer', action='store_true', help='Authorization 加 Bearer 前缀')
    ap.add_argument('--login-only', action='store_true', help='只验证登录拿 token')
    ap.add_argument('--diagnose', action='store_true', help='试多种鉴权方式找能连上的那种')
    a = ap.parse_args()

    token = a.token
    if not token:
        if not (a.account and a.password):
            raise SystemExit('需 --token，或 --account + --password')
        token = login(a.account, a.password)
        print(f'[login] OK，token 前 24 位：{token[:24]}…', file=sys.stderr)

    if a.login_only:
        print('[done] 仅登录验证完成。', file=sys.stderr)
        return
    if a.diagnose:
        if not a.pod:
            raise SystemExit('诊断需 --pod')
        asyncio.run(diagnose(token, a.cluster, a.namespace, a.pod))
        return
    if not a.pod:
        raise SystemExit('开终端需 --pod <pod 名>')
    # 容器名缺省：pod 名去掉末两段副本后缀（app-2c-5856ff577c-jf8qd → app-2c）
    container = a.container or '-'.join(a.pod.split('-')[:-2]) or a.pod
    asyncio.run(open_terminal(token, a.cluster, a.namespace, a.pod, container, a.bearer))


if __name__ == '__main__':
    main()
