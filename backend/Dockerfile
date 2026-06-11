# Falcon 主控（Django 后端）镜像。
# 形态：单进程 waitress（多线程）跑 WSGI —— RunExecutor 用进程内 threading.Thread +
# 模块级 RUN_EXECUTORS dict，所以后端**只能单进程**（K8s 里 replicas=1）。waitress 一个
# 进程 + 线程池正好契合：并发请求走线程，共享同一个 RUN_EXECUTORS（gunicorn 多 worker
# 会让 cancel/metrics 跨进程找不到 executor）。
#
# 内置 Java 17 + JMeter 5.6.3（master 自己跑 Step2 校验 / 本地兜底压测都 spawn jmeter）
# + sshpass（SSH 型压力机 + 反向隧道）。
#
# 构建：docker build -f backend/Dockerfile -t <registry>/falcon-backend:<tag> backend/
# arthas ws 代理复用本镜像，K8s 里换 command 跑 scripts/arthas_ws_proxy.py（sidecar）。

# bookworm(Debian 12)固定：trixie 已下掉 openjdk-17(只剩 21)。JMeter 5.6.3 标准跑
# Java 17(与 Mac openjdk@17 / agent eclipse-temurin:17 对齐)。
FROM python:3.12-slim-bookworm

ARG JMETER_VERSION=5.6.3
# services/jmeter.py 读 JMETER_VERSION（默认 5.4.1）拼 jmeter 目录，必须设成 baked 的版本
ENV JMETER_VERSION=${JMETER_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_DEBUG=0

WORKDIR /app

# 系统依赖：Java17（跑 jmeter）+ sshpass（SSH 压力机）+ 下载工具。
# psycopg-binary 自带 C 库，无需 libpq-dev。
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless sshpass wget unzip curl ca-certificates tini && \
    rm -rf /var/lib/apt/lists/*

# JMeter 5.6.3 + 插件 baked 到 /app/jmeter/apache-jmeter-<ver>/（路径对齐 services/jmeter.py
# 的 BASE_DIR/jmeter/apache-jmeter-<ver>/，BASE_DIR=/app）。runtime 检测到 bin/jmeter 已存在
# → ensure_jmeter_installed() 直接返回，不触发下载。
RUN mkdir -p /app/jmeter && \
    wget -q "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.zip" -O /tmp/jmeter.zip && \
    unzip -q /tmp/jmeter.zip -d /app/jmeter && \
    rm /tmp/jmeter.zip && \
    chmod +x "/app/jmeter/apache-jmeter-${JMETER_VERSION}/bin/jmeter" && \
    cd "/app/jmeter/apache-jmeter-${JMETER_VERSION}/lib/ext" && \
    wget -q https://repo1.maven.org/maven2/kg/apc/jmeter-plugins-casutg/2.10/jmeter-plugins-casutg-2.10.jar && \
    wget -q https://repo1.maven.org/maven2/kg/apc/jmeter-plugins-cmn-jmeter/0.6/jmeter-plugins-cmn-jmeter-0.6.jar

# Python 依赖（requirements 已含 waitress；whitenoise 托管 admin/DRF 静态）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt whitenoise

# 应用代码（.dockerignore 排除 venv / 本地 jmeter / db.sqlite3 / .env / media / runs）
COPY . .

# 收集静态（admin/DRF/jazzmin），whitenoise 在 Django 进程内托管。
# 用临时 SECRET_KEY 避免 collectstatic 阶段报错；不连 DB。
RUN DJANGO_SECRET_KEY=build-time-collectstatic python manage.py collectstatic --noinput

EXPOSE 8000

# tini 当 PID 1 → 正确把 SIGTERM 转发给 waitress / jmeter 子进程
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["waitress-serve", "--threads=8", "--listen=0.0.0.0:8000", "config.wsgi:application"]
