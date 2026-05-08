# falcon-agent 镜像（v1.2）
# 形态：单进程 FastAPI（agent.main） + 内置 JMeter 5.6.3（含 plugins-casutg / cmn-jmeter）
# 主控调 POST /runs 时，spawn jmeter 子进程跑分片任务 → /jtl 拉回合并
#
# 构建：cd backend && docker compose -f docker-compose.dev.yml build agent
# 启动：docker compose -f docker-compose.dev.yml up -d --scale agent=2 agent

# eclipse-temurin:17-jre 多架构（amd64 + arm64），Mac Apple Silicon 也能拉
FROM eclipse-temurin:17-jre

ARG JMETER_VERSION=5.6.3
ENV JMETER_VERSION=${JMETER_VERSION}
ENV JMETER_HOME=/opt/apache-jmeter-${JMETER_VERSION}
ENV PATH="${JMETER_HOME}/bin:${PATH}"

# Python + 工具：debian-based，apt 装；--break-system-packages 只在容器里 OK
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
        wget unzip bash tini ca-certificates && \
    python3 -m venv /opt/agent-venv && \
    /opt/agent-venv/bin/pip install --no-cache-dir --upgrade pip && \
    rm -rf /var/lib/apt/lists/*

# 装 JMeter（无插件主体）
RUN wget -q https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.zip -O /tmp/jmeter.zip && \
    unzip -q /tmp/jmeter.zip -d /opt && \
    rm /tmp/jmeter.zip && \
    chmod +x ${JMETER_HOME}/bin/jmeter

# 装 JMeter 插件（与主控 setup_jmeter 命令对齐）
RUN cd ${JMETER_HOME}/lib/ext && \
    wget -q https://repo1.maven.org/maven2/kg/apc/jmeter-plugins-casutg/2.10/jmeter-plugins-casutg-2.10.jar && \
    wget -q https://repo1.maven.org/maven2/kg/apc/cmn-jmeter/0.6/cmn-jmeter-0.6.jar

# 安装 agent 依赖
COPY agent/requirements.txt /tmp/agent-requirements.txt
RUN /opt/agent-venv/bin/pip install --no-cache-dir -r /tmp/agent-requirements.txt && \
    rm /tmp/agent-requirements.txt

# 拷 agent 入口
COPY agent /opt/agent
WORKDIR /opt

# 默认环境（可被 docker-compose environment 覆盖）
ENV FALCON_AGENT_PORT=9100 \
    FALCON_MASTER_URL=http://web:8000 \
    FALCON_MAX_VUSERS=100 \
    FALCON_AGENT_RUN_DIR=/var/falcon/runs \
    FALCON_ORCHESTRATOR_TYPE=docker

EXPOSE 9100

# tini 当 PID 1，正确转发 SIGTERM 给 uvicorn 让 cancel/优雅停机生效
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/agent-venv/bin/python", "-m", "agent.main"]
