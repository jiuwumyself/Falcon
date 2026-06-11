# Falcon 前端镜像（多阶段）：node 构建 → nginx 托管静态 + 反代后端。
# 前端全相对路径（api.ts BASE=/api/performance；PodTerminal 用 location.host/arthas-term），
# 所以 nginx 把 /api 反代到后端、/arthas-term 反代到 arthas sidecar 即可，前端零改。
#
# 构建：docker build -f frontend/Dockerfile -t <registry>/falcon-frontend:<tag> frontend/

# ── stage 1: 构建 ──────────────────────────────────────────────
FROM zhihuishu-container-images-registry.cn-hangzhou.cr.aliyuncs.com/zhihuishu-base-image/node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# vue-tsc -b && vite build → dist/（vite 默认 outDir，无自定义 base）
RUN npm run build

# ── stage 2: nginx 托管 ────────────────────────────────────────
FROM zhihuishu-container-images-registry.cn-hangzhou.cr.aliyuncs.com/zhihuishu-base-image/nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
