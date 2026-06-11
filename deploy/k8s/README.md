# Falcon K8s 部署

性能压测平台容器化部署到 K8s。架构：前端 nginx(SPA+反代) → 后端 waitress(Django，**单 pod**) + arthas sidecar + 容器化压力源 falcon-agent + 集群内 InfluxDB + 外部 Postgres。

## ⚠ 关键约束
- **后端只能 1 个 pod**（`replicas=1` + `Recreate`）：RunExecutor 用进程内线程 + 模块级 dict，多 pod/多 worker 会让取消/实时指标跨进程失效。pod 重启会丢正在跑的 run。
- **K8sAdapter 仍是 stub**：前端"+扩容"按钮不可用。加压力机用 `kubectl -n falcon scale deployment falcon-agent --replicas=N`，agent 起来自动注册。

## 部署步骤

### 1. 构建 + 推镜像（替换 REGISTRY 为公司 registry）
```bash
REG=harbor.zhihuishu.com/devops      # ← 改成真实 registry
docker build -f backend/Dockerfile  -t $REG/falcon-backend:latest  backend/
docker build -f frontend/Dockerfile -t $REG/falcon-frontend:latest frontend/
docker build -f backend/agent/Dockerfile -t $REG/falcon-agent:latest backend/
docker push $REG/falcon-backend:latest
docker push $REG/falcon-frontend:latest
docker push $REG/falcon-agent:latest

# 把清单里的 REGISTRY 占位替换成真实 registry
grep -rl 'REGISTRY/falcon' deploy/k8s | xargs sed -i '' "s#REGISTRY/#$REG/#g"   # mac sed
```

### 2. 填配置
- `00-namespace-config.yaml`：`DB_HOST`(外部 Postgres 地址)、`DJANGO_ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`(真实域名)
- `50-ingress.yaml`：`host`(真实域名)、`ingressClassName`
- PVC（10/20-*.yaml）：需要时填 `storageClassName`

### 3. 建 Secret（真值不进 git）
```bash
kubectl create namespace falcon
kubectl -n falcon create secret generic falcon-secrets \
  --from-literal=DJANGO_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')" \
  --from-literal=DB_PASSWORD='<Postgres 密码>' \
  --from-literal=FALCON_AGENT_TOKEN="$(python3 -c 'import secrets;print(secrets.token_hex(16))')" \
  --from-literal=ZAPP_ACCOUNT='<zapp 账号>' \
  --from-literal=ZAPP_PASSWORD='<zapp 密码>'
kubectl -n falcon create secret generic falcon-ssh-pw \
  --from-literal=.lgpw='<SSH 压力机密码>'
```

### 4. apply
```bash
kubectl apply -f deploy/k8s/00-namespace-config.yaml
kubectl apply -f deploy/k8s/10-influxdb.yaml
kubectl apply -f deploy/k8s/20-backend.yaml      # initContainer 自动 migrate + setup_influxdb
kubectl apply -f deploy/k8s/30-frontend.yaml
kubectl apply -f deploy/k8s/40-agent.yaml
kubectl apply -f deploy/k8s/50-ingress.yaml
```

### 5. 建 admin 超管（进后台配 Environment / BackendListener）
```bash
kubectl -n falcon exec deploy/falcon-backend -c web -- python manage.py createsuperuser
```

## 验证
```bash
kubectl -n falcon get pods                       # 全 Running
kubectl -n falcon logs deploy/falcon-backend -c web
curl -I https://<域名>/                          # 前端
curl https://<域名>/api/performance/environments/ # 后端 API
```
浏览器进域名 → 建任务 → 跑 → 看实时 Trends。多机：`kubectl -n falcon scale deployment falcon-agent --replicas=3`。

## 注意
- **SSH 型压力机**：后端 pod 要能 SSH 出集群到压力机(NetworkPolicy 放行 22)；反向隧道转发目标已改成 InfluxDB service(代码 `services/ssh.py`)。
- **arthas sidecar** 要能出网到 `zapp-server.zhihuishu.com`。
- **DB 迁移**：每次后端 pod 启动 initContainer 自动跑 migrate（幂等）。
