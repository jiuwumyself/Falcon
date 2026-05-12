# Falcon 项目上下文

## 1. 项目是什么

**Falcon（猎鹰）**：一个**性能压测调度平台**。

**严格限定的范围**：只做性能压测任务的创建、调度、执行、结果查看。**不做** UI 测试、接口测试、认证登录、多租户、复杂权限。前端界面虽然留了 "UI 板块 / 接口板块" 的占位 tab（figma 设计如此），但这些 tab 只是空壳，不要扩展它们。

## 2. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | Vue 3.5 + TypeScript + Vite 8 | `<script setup>` Composition API |
| 样式 | Tailwind v4 + CSS 变量 | 无 `tailwind.config.js`，用 `@theme inline` 写在 `style.css` |
| 动画 | `motion-v` 2.2 | Vue 版 framer-motion，API 接近但用 `<Motion>` 组件 |
| 代码编辑器 | `@guolao/vue-monaco-editor` | Monaco 的 Vue 包装，用于只读展示 JMX XML |
| 图标 | `lucide-vue-next` | |
| 路由 | `vue-router` 4 | |
| 后端 | Django 5.1 + DRF | 已装 `djangorestframework-simplejwt` 但**未启用**（平台暂不做认证）|
| 压测引擎 | **JMeter**（通过 `.jmx` 文件驱动）| 前端上传 JMX → 后端用 `lxml` 解析/打补丁 |
| XML 处理 | `lxml` 6.x | 后端解析/修改 JMX 的核心库 |
| 数据库 | SQLite（默认）/ PostgreSQL（通过 `.env` 切换）| psycopg 已装 |
| Python | 3.12（venv 在 `backend/venv`）| |

## 3. 目录结构

```
Falcon/
├── backend/               Django 项目
│   ├── config/           settings.py、urls.py、wsgi.py、asgi.py
│   ├── performance/      ✅ 业务 app（v1 已落地）—— 性能压测领域；原名 `tasks`，2026-04-23 按板块拆分重命名
│   │   └── scripts 存放在 `backend/jmeter/apache-jmeter-<VERSION>/scripts/`
│   │       JMX 和 CSV 文件**都在这里**（CSV 命名 `<jmx_stem>__<safe_path>.csv`，按 CSVDataSet 组件 path 绑定）
│   │   ├── models.py            Task (含软删除) / TaskCsvBinding / TaskRun / MetricSample / Environment
│   │   ├── serializers.py       DRF 序列化（含 status 计算字段 + csv_bindings 嵌套）
│   │   ├── views.py             TaskViewSet（CRUD + components/upload-csv 等 + preview-run-xml）
│   │   ├── urls.py              DefaultRouter
│   │   ├── admin.py             用 Task.all_objects 展示含软删；TaskCsvBinding 内嵌
│   │   ├── services/
│   │   │   ├── jmx.py           ★ JMX L1 编辑（parse_jmx / patch_jmx / 组件树 / TG 替换 / build_run_xml）
│   │   │   ├── jmeter.py        ★ JMeter 工具下载 + 脚本/CSV/runs 目录 + 磁盘检查
│   │   │   ├── jmeter_runner.py ★ JMeter 子进程封装 + JTL CSV 解析（Step 2 校验 + Step 3 跑压测共用）
│   │   │   ├── validator.py     ★ Step 2 校验：build_validate_xml → run_jmeter -n → 解析 JTL → ValidateResult[]
│   │   │   ├── executor.py      ★ Step 3 RunExecutor（v1.1 单机；v1.2 分布式分支共用）
│   │   │   ├── scheduler.py     ★ v1.2 多机调度（compute_shards / build_shard_jmx / slice_csv_by_offset）
│   │   │   ├── jtl_merger.py    ★ v1.2 多 jtl 流式 N-way merge by timeStamp
│   │   │   └── orchestrator/    ★ v1.2 容器编排适配器：DockerComposeAdapter / K8sAdapter（stub）
│   │   ├── management/commands/
│   │   │   ├── setup_jmeter.py          手动预装 JMeter（或首次上传时自动下载）
│   │   │   └── release_idle_agents.py   v1.2 周期任务：心跳超时 → scale_down + 标 LOST
│   │   ├── tests/fixtures/      sample.jmx（parse/patch 测试用）
│   │   └── migrations/          0001 ~ 0010（最新：0010_load_generator）
│   ├── agent/            ★ v1.2 falcon-agent 容器化压力源（FastAPI + 内置 JMeter）
│   │   ├── main.py       入口 = FastAPI app（startup 自注册 + heartbeat 守护线程 + /runs 等端点）
│   │   ├── Dockerfile    eclipse-temurin:17-jre-alpine + JMeter 5.6.3 + 插件 + tini
│   │   └── requirements.txt   fastapi/uvicorn/psutil/requests/python-multipart
│   ├── jmeter/           **JMeter 工具 + 脚本存储**（apache-jmeter-5.6.3/ gitignored）
│   │   └── apache-jmeter-5.6.3/scripts/   ★ 所有上传的 .jmx 物理存放在这里
│   ├── media/            只存 CSV 了（jmx 走 jmeter/scripts，整个 media/ gitignored）
│   ├── docker-compose.dev.yml   v1.1 InfluxDB v1.8 + v1.2 falcon-agent（默认 1 副本，scale 改副本数）
│   ├── manage.py
│   ├── db.sqlite3        默认数据库（gitignored）
│   ├── .env.example      环境变量模板
│   ├── requirements.txt
│   └── venv/             Python 虚拟环境（gitignored）
├── frontend/              Vue 项目
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── style.css                全局 CSS 变量 + Tailwind
│   │   ├── layouts/AppLayout.vue    包 provideTheme()，渲染 RouterView
│   │   ├── pages/
│   │   │   ├── LoginPage.vue        粒子动画登录页（点按钮直接跳 /home，无鉴权）
│   │   │   └── HomePage.vue         主仪表板，tabs: 概览 / 性能 / UI / 接口
│   │   ├── router/index.ts          无 auth guard，只有 / 和 /home
│   │   ├── composables/useTheme.ts  provide/inject 主题上下文（dark/light）
│   │   ├── lib/
│   │   │   ├── api.ts               ✅ v1 新增：极简 fetch 封装（无 auth）
│   │   │   └── utils.ts             cn() 合并 class
│   │   ├── types/task.ts            ✅ v1 新增：Task/TaskRun/Paginated 类型
│   │   ├── components/
│   │   │   ├── FalconLogo.vue
│   │   │   ├── ParticleCanvas.vue   登录页左侧粒子画布
│   │   │   ├── GlassNav.vue         玻璃拟态容器
│   │   │   ├── PerformanceStage.vue 性能板块：三列主布局（mock 数据） + Wizard 模式（真业务），二选一显示
│   │   │   ├── tasks/               ✅ v1 已落地
│   │   │   │   ├── TaskCreateWizard.vue    5 步向导（单面板 + 左竖脊 stepper + 右内容）
│   │   │   │   ├── ScriptTree.vue          Step 1 已上传后的 JMX 组件树 view（拉 /components/，用 ComponentNode 递归）
│   │   │   │   ├── ComponentNode.vue       组件树单行（chevron + testname + tag + enabled 开关）
│   │   │   │   ├── ConfigStage.vue         Step 2 根组件（TG 切换器 + 场景 tabs + 左参数/右图 + 校验结果 + ServicePicker）
│   │   │   │   ├── ExecuteStage.vue        Step 3 根组件（RunControlBar + RunDashboard + StartRunModal）
│   │   │   │   ├── configStageCtx.ts       6 个场景定义（SCENARIOS 数组：id / label / color / icon / kind / defaultParams）
│   │   │   │   ├── config/                 Step 2 子组件：ScenarioTabs / ThreadGroupPicker / TgParamsForm / ThreadGroupChart（echarts）/ EnvironmentPicker / ServicePicker（v1.2）/ ValidateResultTable
│   │   │   │   └── execute/                Step 3 子组件：RunControlBar / RunDashboard / StartRunModal（多机选）/ LoadGeneratorPicker / SystemMetricsModal / SamplerStatsTable / ErrorDetailList / GrafanaPanelViewer / RuntimeStatusPanel + dashboard/（TrendsTab / SamplersTab / ErrorsTab / TimelineTab / PreCheckTab / ServicePanelsTab / TracePanelsTab）
│   │   │   ├── home/                HeroSection、ZoomSection、AnimNum、Spark、ScrollDots
│   │   │   └── perf/                ChronosNerve、MetricsColumn、TemporalColumn、Anim、WaveSpark、
│   │   │                            GlassSkeleton、data.ts（**mock 仍存在，但新业务走 API**）、
│   │   │                            useRimColor.ts
│   │   └── assets/
│   ├── vite.config.ts      @ → src/，/api → http://localhost:8000 代理
│   └── package.json
├── figma/                 **原始 React/TSX 设计源**（参考用，不要修改，也不要在运行时引用）
├── start.sh / stop.sh     **Mac** 一键启停（终端跑 `./start.sh`，Ctrl+C 停止）
├── start.bat / stop.bat   Windows 一键启停（双击 .bat）
└── CLAUDE.md              本文件
```

## 4. 如何运行

### 一键启动/关闭（推荐）

**Mac**（项目根目录）：
- `./start.sh` — 后台起 Django + Vite，Ctrl+C 同时停两端
- `./stop.sh` — 按端口（8000/5173/5174/5175）杀残留进程

**Windows**（项目根目录双击）：
- `start.bat` — 在两个新 CMD 窗口分别起 Django（:8000）和 Vite（:5173）
- `stop.bat` — 按端口（8000/5173/5174/5175）杀进程

### 手动命令

**前端**（在 `frontend/` 下，跨平台）：
```bash
npm run dev              # Vite dev server → http://localhost:5173
npm run build            # 会先跑 vue-tsc -b，再 vite build
npx vue-tsc --noEmit     # 仅类型检查
```

**后端**（在 `backend/` 下，用 venv 里的 Python）：
```bash
# Mac / Linux
./venv/bin/python manage.py runserver    # http://localhost:8000
./venv/bin/python manage.py migrate
./venv/bin/python manage.py check
./venv/bin/pip install -r requirements.txt

# Windows
./venv/Scripts/python.exe manage.py runserver
./venv/Scripts/python.exe manage.py migrate
./venv/Scripts/python.exe manage.py check
./venv/Scripts/pip.exe install -r requirements.txt
```

**前后端连通**：Vite 把 `/api/*` 代理到 `localhost:8000`；Django 的 CORS 放行了 `localhost:5173` / `127.0.0.1:5173`。

## 5. 当前真实状态（重要）

**v1.2 容器化压力源 + Dashboard 重构 已落地（端到端已验证）**（2026-05-07 骨架；2026-05-13 多机联调通过 commit 18407d9）：

### 容器化压力源（LoadGenerator）+ 多机调度

- ✅ **`LoadGenerator` 模型**（migration 0010）：`pod_name`（unique）/ `ip:port` / `token` / `status`（pending/idle/busy/lost）/ `cpu_cores` / `memory_gb` / `max_vusers`（默认 100）/ `orchestrator_type` / `last_heartbeat_at`。`TaskRun` 加 M2M `load_generators` 记录这次 run 用了哪几台
- ✅ **`backend/agent/`** = 单进程 FastAPI + 内置 JMeter 5.6.3（含 plugins-casutg / cmn-jmeter）的容器镜像。`agent/main.py` startup 自调主控 `register/`，30s 心跳；端点 `POST /runs` 起 jmeter 子进程 / `POST /runs/:id/cancel` graceful + SIGKILL / `GET /jtl` 给主控合并 / `GET /system-metrics` psutil 实时 CPU/Mem/IO
- ✅ **`docker-compose.dev.yml` 拆 agent1/agent2/agent3 三个独立 service**（2026-05-13 重构）：固定 host port 9100/9101/9102，`FALCON_AGENT_REPORT_PORT` 注入对应值让 agent 注册时上报正确 host port。要更多机器复制 agent3 段递增端口即可。`extra_hosts: host.docker.internal:host-gateway` 让 Linux 容器也能回调宿主主控。**不再用 `--scale`**（单机 dev 下会撞 host port）
- ✅ **`services/orchestrator/`** = OrchestratorAdapter 抽象 + `DockerComposeAdapter`（subprocess 调 docker compose）+ `K8sAdapter`（v1.3 stub）；`factory.get_adapter()` 按 `settings.ORCHESTRATOR_TYPE` 选实现
- ✅ **`services/scheduler.py`**：`compute_shards`（按 max_vusers 容量分配 vusers）+ `build_shard_jmx`（复用 `build_run_xml` 后逐 TG 改 num_threads + BackendListener 加 `host=pod_name` tag）+ `slice_csv_by_offset`（行偏移切片，留接口位）
- ✅ **`services/jtl_merger.py`**：多 jtl 流式 N-way merge by timeStamp，O(N) 内存
- ✅ **`services/executor.py` 加分布式分支**：`_select_load_generators()` 拉 TaskRun.load_generators → 非空走 `_run_distributed`（每台 POST /runs → 1s 轮询所有 agent 终态 → GET /jtl 拉回 → `merge_jtls` 写到 run_dir/results.jtl），空 + `LOCAL_FALLBACK=1` 走原 v1.1 单机流程。`cancel()` 同时广播到所有 agent
- ✅ **API 端点（`/api/performance/load-generators/`）**：
  - `GET /` → 列出全部 LoadGenerator（前端 StartRunModal 用）/ `GET /:id/`
  - `POST /register/` → agent 自注册 upsert（按 pod_name 唯一）
  - `PUT /:id/heartbeat/` → agent 周期心跳；lost 收到心跳自动复活回 idle
  - `POST /scale-up/` body `{count}` → 调编排适配器拉副本
  - `POST /scale-down/` body `{pod_names?}` 或 `{idle_only: true}` → 释放容器 + 标 LOST
  - `GET /:id/system-metrics/` → 主控代理到 agent `/system-metrics`（5s timeout，不可达 → 503）
- ✅ **Bearer 共享 token**：`settings.FALCON_AGENT_TOKEN` 配置后 register/heartbeat 走 `Authorization: Bearer …` 校验；空 token = 不强校验（开发态 curl 调试方便）
- ✅ **`TaskViewSet.run` 加 `load_generator_ids`**：前端从 StartRunModal 选机器 → POST `/tasks/:id/run/` body `{load_generator_ids: [..]}`；空数组 + `LOCAL_FALLBACK=1` → executor 走单机本地兜底
- ✅ **`manage.py release_idle_agents`**：心跳超 `IDLE_RELEASE_MINUTES`（默认 30）的 idle agent → scale_down + 标 LOST；建议 cron 每 5 min 跑一次
- ✅ **`settings.py` 新增**：`ORCHESTRATOR_TYPE` / `AGENT_COMPOSE_*` / `AGENT_K8S_*` / `MAX_VUSERS_PER_AGENT` / `IDLE_RELEASE_MINUTES` / `FALCON_AGENT_TOKEN` / `LOCAL_FALLBACK`

### Step 2：被压测服务（service_names 多选）

- ✅ **`Task.service_names`**（JSONField default=list；migration 0008 加 `service_name` → 0009 数据搬到 `service_names` + 删旧字段）：服务库目前是**前端 mock**（`frontend/src/lib/servicesMock.ts`），v1.3 接后端 Service 表后改 M2M
- ✅ **前端 `ServicePicker.vue`**：多选下拉，PATCH `/tasks/:id/` body `{service_names}` 单字段轻改（与 thread-groups 端点解耦）
- ✅ **`tasksApi.update()`** 通用 PATCH 助手

### Step 3：真端点替代 mock + Dashboard 重构

- ✅ **三个新只读端点**：
  - `GET /runs/:run_id/sampler-stats/` → 优先读 JMeter HTML 报告 `statistics.json`，没有时流式扫 jtl 自聚合（avg/min/max/p50/p90/p99/RPS/bytes/top errors）
  - `GET /runs/:run_id/error-samples/?limit=&sampler=&code_bucket=` → 流式扫 jtl `success=false` 行；按 sampler / code_bucket（4xx/5xx/assertion/timeout/all）过滤
  - `GET /runs/:run_id/timeline/` → 阶段轴：`pre_check / ramp_up / steady / cool_down`
- ✅ **`build_run_xml` + `_inject_backend_listener` 加 `extra_backend_tags`**：分布式时给每片 jmx 加 `host=pod_name` tag
- ✅ **前端 ExecuteStage 重构**：原来"竖直堆叠 6 块"换成 `RunControlBar`（单行紧凑控制条）+ `RunDashboard`（占满剩余高度的 7 个 tab：Trends / Samplers / Errors / Timeline / PreCheck / ServicePanels / TracePanels）+ `StartRunModal`（必选压力源）
- ✅ **`StartRunModal`**：列出 idle agent + 容量校验（合计 max_vusers ≥ task.virtual_users）+ 「+ 扩容」按钮（调 `loadGeneratorsApi.scaleUp`）
- ✅ **`SystemMetricsModal`**：弹窗轮询 agent psutil 实时 CPU/Mem/Net/Disk IO

### v1.2 多机端到端联调（2026-05-13，commit 18407d9）

5 件套 fix 后端到端跑通（task vu=1 + 3 agent，run `9648ad3d7e31fa73`）：
- ✅ **#1 compute_shards 改吃 thread_groups_config 聚合**：原拿 `task.virtual_users`（jmx parse 初值，多 TG 失真）→ 单 TG 1 vu 多 TG 实际 10 vu，shares=[1,0,0] 只塞第 1 台。新增 `scheduler.compute_planned_vusers_total()` + `_planned_vusers_for_tg()`，executor 调用方改吃聚合值；`views._compute_tg_planned_users` 复用同源逻辑（single source of truth）
- ✅ **#2 agent /jtl + /errors-xml 改 StreamingResponse + size snapshot**：FileResponse 把打开时 stat.st_size 写到 Content-Length，JMeter 边写边读时实际字节多 → `RuntimeError: Response content longer than Content-Length`。snapshot size 后只读这么多字节，下游 csv 按行容忍尾部半行
- ✅ **#3 `start.sh` 加 release_idle_agents 周期回收**：bg loop 每 5 min 跑一次，僵尸 agent（30 min 无心跳）自动标 lost
- ✅ **#4 CSV slice 串接 executor + `settings.CSV_SLICE_ENABLED` 开关**：`scheduler.slice_csv_by_offset` 早实现了接口位但 executor 没调用。默认 False 保持现有"全量副本"行为（字典表 / 共享参数场景），env 设 `CSV_SLICE_ENABLED=true` 开启按行模分片（账号池场景）。失败兜底全量副本不阻断 run
- ✅ **#5 compose 拆 3 service**：见上面 docker-compose.dev.yml 那条

验证数据：jtl 3 份均衡（3629/3649/3617）+ InfluxDB `shard_count=3` + 3 个 host tag + 每 host samples 222/222/222 + agent log Content-Length 错误 0 次。

### v1.2 待跟进

- ❓ 前端 host 切分图：后端 InfluxDB host tag 数据完备，前端 `RunMetricsCharts` / dashboard `TrendsTab` 按 host 切线 UI 没现场看过——多 agent 跑时图表是否真把 3 条线分开
- ❓ Service 模型仍是前端 mock（`servicesMock.ts`）；v1.3 接真表
- ❌ per-binding CSV slice 控制（当前 `CSV_SLICE_ENABLED` 是全局开关，粒度粗，将来给 TaskCsvBinding 加字段）

---

**v1.1 Step 3 已落地**（2026-04-30，分支 `feat/step2-polish`）：

### Step 3 执行任务（JMeter 子进程编排 + 实时指标）

- ✅ **`TaskRun` 字段扩展**：加 `run_id`（短 uuid，面向用户）/ `pre_check_log` / `pid` / `stop_port` / `last_heartbeat_at` / `cancel_requested_at` / `archived_at`；状态枚举扩 4 个：`pre_checking` / `pre_check_failed` / `cancelling` / `timeout`（同时 `fail` 改名 `failed`）；DB 唯一约束 `unique_active_run_per_task`（同 task 串行兜底）
- ✅ **`services/executor.py` RunExecutor**：threading.Thread daemon=False 起子线程编排 pre_check → spawn JMeter → heartbeat + 取消监听 → 解析 .jtl 总结 → 归档。每个 run 独立线程 + 子进程；不限全局并发；同 task 串行（DB 唯一约束 + 409 Conflict）
- ✅ **取消语义 = graceful 30s + SIGKILL 兜底**：先连 JMeter 的 nongui.port 发 `StopTestNow`；30s 没退升级 SIGTERM → SIGKILL（Mac/Linux 走 `os.killpg(getpgid)`，Windows 走 `proc.terminate/kill`）
- ✅ **实时指标 = JMeter Backend Listener → InfluxDB v1.8**：JMX 注入 `<BackendListener>` 节点（v1 协议 POST `/write?db=jmeter`）；前端 3s 轮询 `GET /runs/:run_id/metrics/`；按 transaction 切 TG 分组；MetricSample 表保留作降级路径但不再写入
- ✅ **磁盘归档 + 压缩**：每 run 一个目录 `<jmeter_home>/runs/<run_id>/{run.jmx, results.jtl, jmeter.log, report/}`；保留最新 20 个，更老的整目录 gzip 成 `<run_id>.tar.gz`
- ✅ **预检 = 5 项**：JMeter 二进制 / JMX + Step 2 配置完整 / `build_run_xml` 试运行 / 磁盘空间 ≥ 100 MB / InfluxDB ping 通过 / Environment hosts TCP 探测（非致命）
- ✅ **API 端点**：
  - `POST /api/performance/tasks/:id/run/` → 创建 TaskRun + 起 RunExecutor；同 task 已活跃 run 时返 409 Conflict + active_run_id
  - `GET /api/performance/tasks/:id/runs/` → 该 task 全部 run（分页）
  - `GET /api/performance/runs/:run_id/` → 单 run 详情
  - `POST /api/performance/runs/:run_id/cancel/` → graceful cancel；终态时幂等返 200
  - `GET /api/performance/runs/:run_id/metrics/?since=...` → `{overall, by_tg, last_ts, run}` 时序点
  - `GET /api/performance/runs/:run_id/log/?tail=N` → JMeter log 末 N 行
  - `GET /api/performance/runs/:run_id/jtl/` → 二进制 results.jtl 下载
  - `GET /api/performance/runs/:run_id/report/[<sub>]` → JMeter `-e -o` 生成的 HTML 报告（iframe 用）
- ✅ **前端 Step 3 ExecuteStage**：左 1/3 状态卡（状态徽章 + 计时器 + 进度条 + 终态总结 + 开始/取消/查看报告按钮）+ 历史 run 列表；右 2/3 按 TG 切 tab、四张 echarts 图（RPS / P99 / 错误率 / 活跃用户数）+ pre_check_log 面板。运行中 3s 轮询，终态自动停
- ✅ **InfluxDB 部署**：`backend/docker-compose.dev.yml` 起 InfluxDB v1.8；`manage.py setup_influxdb` 建库 + 30d 保留策略

**v1 已落地**（更新 2026-04-28，分支 `feat/step1-step2-polish`）：

### 后端
- ✅ `performance` app：四张表（Task / TaskCsvBinding / TaskRun / MetricSample / Environment）+ DRF ViewSet
- ✅ **软删除**：`Task.is_deleted` + `Task.deleted_at`；`TaskManager`（默认过滤软删） + `all_objects`（admin 看全量）；`DELETE /api/performance/tasks/:id/` 走软删 + 物理删除原件 + 全部 csv_bindings
- ✅ **JMX 物理存储**：上传的 .jmx 落在 `backend/jmeter/apache-jmeter-5.6.3/scripts/<title>.jmx`，不在 `media/`。Task 的 `jmx_filename` CharField 存文件名（不含路径）。代码固定用 `backend/jmeter/apache-jmeter-<VERSION>/`，**不读 `JMETER_HOME` env**（避免被全局 JMeter 装载 hijack）
- ✅ **JMeter 工具**：`performance/services/jmeter.py` 管工具生命周期；`manage.py setup_jmeter` 手动预装；首次用会自动从 `archive.apache.org` 下 JMeter zip（带 SHA-512 校验）；写盘前检查可用磁盘 < 100 MB 拒绝 + `os.fsync()` 强刷盘；新增 `get_runs_dir()` 给 v1.1 执行模块预留
- ✅ **文件名规则**：title 不再加日期前缀（2026-04-28 取消），直接用用户输入；`sanitize_script_name()` 清掉 Windows/Linux 非法字符（`< > : " / \ | ? *` 等），保留中文；冲突追加 `_2`、`_3`
- ✅ **JMX L1 编辑**：`performance/services/jmx.py` 的 `parse_jmx` / `patch_jmx`（patch-in-place）。**宽容解析**：找不到标准 `<ThreadGroup>`（比如用了 `UltimateThreadGroup` 插件）不报错，用默认值 `10/0/60` 兜底。`patch_jmx` 留给后面的"任务配置"模块用（v1 前端已不直接调）
- ✅ **组件树 + enabled 切换**：`performance/services/jmx.py` 的 `list_components` / `toggle_component` + dataclass `JmxComponent`；按 JMeter 的 `<hashTree>` 配对结构递归遍历所有组件，用索引路径（如 `"0.2.1"`）定位元素、改 `enabled` 属性
- ✅ **组件树 UI**：前端 `ScriptTree.vue` + `ComponentNode.vue`。默认展开到 3 级、更深手动展开；TestPlan 根节点无 toggle，该行承载**搜索框 + 全部展开 + 全部折叠**工具栏；搜索匹配淡黄高亮 + 自动展开祖先路径（不隐藏不匹配项）
- ✅ 核心 API 端点（在 `/api/performance/tasks/`）：
  - `POST /api/performance/tasks/`（multipart，含 `jmx_file`）→ 解析 → 落盘到 scripts/ → 建 Task
  - `GET /api/performance/tasks/`、`GET /api/performance/tasks/:id/`（默认过滤软删）
  - `PATCH /api/performance/tasks/:id/`（改 title 会 rename 文件；改 vuser/ramp/duration 会 `patch_jmx` 重写文件内容）
  - `DELETE /api/performance/tasks/:id/` → 软删 + 物理删除 .jmx
  - `POST /api/performance/tasks/:id/replace-jmx/`（multipart，含新 `jmx_file`）→ 覆盖原件；title / biz / description / created_at 保留；**自动清空 `thread_groups_config` + 解绑全部 csv_bindings + 删物理 CSV 文件**（2026-04-28：脚本结构变多半失效，简单清空更稳）
  - `GET /api/performance/tasks/:id/raw-xml/` → `{ xml: "..." }`
  - `GET /api/performance/tasks/:id/download/` → 二进制 JMX
  - `GET /api/performance/tasks/:id/preview-run-xml/` → `{ xml }` 把内存生成的可执行版返给前端预览（不写盘）
  - `GET /api/performance/tasks/:id/components/` → 组件树（JmxComponent[]，每项含 `kind` 字段；**BackendListener 自动过滤**）
  - `POST /api/performance/tasks/:id/components/toggle/` body `{path, enabled}` → 切换单个组件 enabled
  - `POST /api/performance/tasks/:id/components/rename/` body `{path, testname}` → 改 testname
  - `GET /api/performance/tasks/:id/components/detail/?path=...` → 8 种可编辑组件字段（HTTPSampler / HeaderManager / HttpDefaults / JSONPathAssertion / BeanShell Pre+Post / RegexExtractor / JSONPathExtractor / CSVDataSet；**CSVDataSet 不含 filename**）
  - `PATCH /api/performance/tasks/:id/components/detail/` body `{path, kind, fields}` → 写回字段（同上 8 种）
  - `POST /api/performance/tasks/:id/components/upload-csv/`（multipart，body `path` + `csv_file`）→ **按 CSVDataSet 的组件 path 绑定** CSV，落盘命名 `<jmx_stem>__<safe_path>.csv`，写 / 更新 `TaskCsvBinding`
  - `POST /api/performance/tasks/:id/components/delete-csv/` body `{path}` → 解除某 CSVDataSet 的绑定（删行 + 删物理文件）
  - `POST /api/performance/tasks/:id/components/upload-jar/`（multipart `jar_file`）→ 写入 JMeter lib/ext/（全局共享，≤ 50 MB）；返回 `{filename, message}`（含远程机手动安装提示）
- ✅ **Step 2 任务配置**（v2 场景驱动 UI；2026-04-28 取消 `_run.jmx` 派生）：
  - `Environment` 模型 + admin（name / is_default / host_entries JSONField）；前端只读下拉，编辑走 `/admin/performance/environment/`
  - Task 字段：`thread_groups_config` (JSONField) / `environment` FK；**已删除 `run_jmx_filename` / `csv_filename`**（前者改为内存生成，后者改为多绑定关联表）
  - 关联表 `TaskCsvBinding(task, component_path, filename)`：每个 CSVDataSet 独立挂 CSV
  - **6 个场景** + 底层 TG 映射（用户只看场景，不看 TG 类型）：
    - 基准 → `ThreadGroup`
    - 负载 / 压力 → `SteppingThreadGroup`
    - 稳定性 → `ConcurrencyThreadGroup`
    - 峰值 → `UltimateThreadGroup`
    - 吞吐量 → `ArrivalsThreadGroup`
  - 参数上限 **用户数 ≤ 5000、时长 ≤ 43200 秒（12h）**；`target_rps` 不按用户数限，上限 1,000,000
  - **单文件模型**：磁盘只存原件 `<title>.jmx`。`services/jmx.py::build_run_xml(task)` 内存里读原件 → 套 thread_groups_config → 套 csv_bindings 绝对路径 → 可选注入 DNSCacheManager → 按 BackendListenerConfig 注入 BackendListener。validate / 未来 run 都吃这份内存 XML
  - **多 TG 独立配置**：每个启用的 TG 单独存 `{path, scenario, kind, params}`；前端 TG 切换器让用户逐个配；禁用的 TG 不显示、保存时原样保留
  - **插件自动下载**：`setup_jmeter` 命令装 `jmeter-plugins-casutg` + `cmn-jmeter` 到 `lib/ext/`（Maven Central）。Ultimate/Arrivals 依赖这俩 JAR
  - **校验 = 真 JMeter 跑（每接口跑 1 次）**：`services/jmx.py::build_validate_xml(task)` 把所有启用的 TG 降级为 1 线程 1 循环的标准 ThreadGroup（保留 Sampler 子树原样）→ 套 CSV 绑定（绝对路径）+ 注入 Environment DNSCacheManager → `services/jmeter_runner.py::run_jmeter(xml, work_dir)` 写到 `<jmeter_home>/runs/_validate_<task_id>/run.jmx` → subprocess `jmeter -n -t run.jmx -l result.jtl` → 解析 JTL CSV → 按 testname (label) FIFO 匹配回 sampler `path`，返回 `ValidateResult[]`。冷启 ~3-5s + 实际请求时间。**保真度 = 100%**（JMeter 自带 CookieManager / AuthManager / Pre-Post Processor / `__time` 等函数 / 完整 JSONPath / BeanShell 等，Python 自实现永远会缺东西）。Step 3 真压测共用同一 `run_jmeter()`
  - 前端图表：**echarts + vue-echarts**（LineChart 按需引入）；Step 3 实时监控图表复用
  - 关键端点：
    - `GET /api/performance/environments/` / `/:id/` → 只读，创建编辑走 admin
    - `GET /api/performance/tasks/:id/thread-groups/` → `{thread_groups, saved_config, environment}`
    - `PATCH /api/performance/tasks/:id/thread-groups/` body `{thread_groups, environment_id}` → 仅入库，**不写盘**
    - `POST /api/performance/tasks/:id/validate/` body `{environment_id?}` → 内存生成 + 1 并发请求

### 前端
- ✅ **任务列表** = 性能板块默认入口（2026-04-28 改造）：`PerformanceStage.vue` mounted 时调 `tasksApi.list()` → 映射成 ChronosNerve 的视觉 schema 渲染。`PEOPLE` / `BIZ` mock 仍作为视觉点缀；`MetricsColumn` / `TemporalColumn` 暂用 mock TASKS 撑视觉（运行时指标 v1.1 接 TaskRun 才有）
  - 列表行**右键** → `TaskContextMenu` 浮层「删除任务」（confirm 后调 `DELETE /tasks/:id/`）
  - 列表行**点击** → 进 wizard 编辑（`router.push('/performance/tasks?id=N')`）
  - 状态徽标：`draft`（灰，仅上传未配置）/ `configured`（紫，已 Step 2）/ 未来 `running` / `success` / `failed`
- ✅ 创建入口：性能板块 ChronosNerve 顶部"+ 创建"渐变按钮 → `router.push('/performance/tasks')`（无 `?id`）
- ✅ Wizard 布局：单一玻璃面板，内部左 104px 竖脊 stepper + 右侧内容区
- ✅ **Step 语义**：
  - **Step 1 上传脚本**：未上传 → dropzone；已上传 → 头部 + `ScriptTree`（组件树 + enabled toggle + **点名称打开编辑抽屉**（8 种）+ 双击改名 + CSVDataSet 行内 Paperclip 上传 + BeanShellPreProcessor 行内 Package 上传 JAR）。重新上传按钮：**已配置 Step 2 时弹 confirm 提醒清空**，上传后 toast 反馈。BackendListener 组件在 UI 不显示（由 Admin 全局配置 + build_run_xml 注入）
  - **Step 2 任务配置** = 场景 tab + 参数表单 + echarts 预览 + JMeter CLI 校验（每接口跑 1 次）。每个场景 pill 旁有 `?` 图标 hover tooltip（用途 / 典型参数 / 关注指标）。多 TG 时顶部 TG 切换器，逐个配
  - **Step 3/4/5 执行/分析/报告** = "v1.1 即将推出"占位
  - 列表点行进 wizard 时跳到**最远完成的 Step**（`thread_groups_config` 非空 → Step 2，否则 Step 1）
- ✅ 只接受 `.jmx`，拖入 / 选择非 jmx 文件会显示"仅支持 .jmx 文件"红字
- ✅ **.jmx 大小硬上限 10 MB**（前端 `TaskCreateWizard.handleFile` 校验；后端 `views.py::create` 校验；`settings.MAX_UPLOAD_SIZE` + `DATA_UPLOAD_MAX_MEMORY_SIZE` + `FILE_UPLOAD_MAX_MEMORY_SIZE` 三道兜底）
- ✅ 错误消息人类化：`api.ts` 的 `ApiError.humanMessage` 把 DRF field error JSON 解析成一行可读文案
- ✅ **API helper**：`lib/api.ts` 导出 `tasksApi`（list / get / delete / uploadComponentCsv / deleteComponentCsv），新业务调用走它
- ✅ **后台入口**：`MainLayout` 主题切换右侧加 Settings 齿轮，新 tab 打开 `/admin/`

**Step 2 仍待改进（v1.0.x 收尾，下一轮排期）**：
- **TG 参数与真实 JMeter 字段对齐**：ArrivalsThreadGroup 的 `ConcurrencyLimit` / `LogFilename` / `Iterations` 当前写死兜底，应让用户能看到、有需要时调；Stepping 的"每步内部 ramp"目前固定 `step_delay/2`，应可显式覆盖
- **Environment hosts 实际写入 DNSCacheManager**：`build_run_xml(inject_environment_dns=True)` 已实现，validate 走的是 request-time host 替换；Step 3 真跑 JMeter 时要默认开启注入。Step 2 应有"预览生成的 XML"按钮（已有 `preview-run-xml` 端点，前端没接 UI）
- **"压测的服务"字段**：当前 Task 没有 service 字段。规划：Task 上加 `service` CharField + Service 模型（name / grafana_url / pinpoint_app / arthus_endpoint 等）；Step 2 选 service → Step 3 执行后据此从 Grafana / Pinpoint 拉指标用于报告对比；服务在监控平台找不到时，落地"基础指标只有 JTL 数据 + 提示用户接入监控"
- **集合点 / 多峰 Ultimate**：Synchronizing Timer 和多行 Ultimate（多峰错峰）v1.2+

**完全没做**（v1.1+）：
- 真正跑 JMeter（`jmeter -n -t <file>.jmx -l results.jtl` CLI 调用 + subprocess）
- 压力机选型（本地 / 远程多机分布式）
- Celery + Redis 异步调度
- MetricSample 时序写入（表建了，表空着）
- 报告 / AI 分析 / Word 导出 / Grafana / Pinpoint / Arthus 接入
- 认证（永远保持 `AllowAny` 直到用户说换）

## 6. 下一步路线（按重要性）

1. ~~**JMeter CLI 执行**~~ ✅ Step 3 已落地（见 §5）
2. ~~**压力机管理**（v1.2）：容器化压力源（FastAPI agent + DockerComposeAdapter）+ 多机调度~~ ✅ 骨架已落地 + 端到端已联调（commit 18407d9）；**前端 host 切分图未现场看，发现问题再修**
3. **Service 模型 + SLA 字段**（v1.3，Step 4 报告前置）：当前 `Task.service_names` 是字符串数组 + 前端 `servicesMock.ts`；v1.3 接后端 Service 表（grafana_url / pinpoint_app / arthus_endpoint / SLA）+ Task 改 M2M
4. **K8sAdapter 实现**（v1.3）：当前 `services/orchestrator/k8s.py` 是 stub，靠 `kubectl scale deployment`；生产部署前需要补
5. **异步化升级**（v1.3）：Celery + Redis 替代 threading；多 worker 横向扩展、子进程管理跨进程持久化
6. **真实时刷新**（v1.3）：当前前端 3s 轮询 `metrics`；改 SSE 或 WebSocket 推送，后端 endpoint 形状不变
7. **Step 4 分析 / Step 5 报告**（v1.3+）：iframe JMeter HTML 报告作为 v1.1 兜底；自画对比页 + AI 总结 + Word 导出留到 v1.3
8. **TG 高级参数暴露**：Arrivals 的 `ConcurrencyLimit`、Stepping 的"每步内部 ramp"等当前写死兜底
9. **CSV 切片落地**：`scheduler.slice_csv_by_offset` 已实现，但 executor 里多机分支当前用全量 CSV 副本；需要决定切片是默认开还是按场景（账号池等）

## 7. 关键约定 & 踩坑点

- **`figma/` 是设计源，不是运行时代码**。frontend 里**不要 import 它**。需要 UI 参考时读它、照着写 Vue 版本。
- **没有鉴权**。路由没 guard，后端 `DEFAULT_PERMISSION_CLASSES = [AllowAny]`。user 明确要求"先不做登录验证"。
- **`djangorestframework-simplejwt` 已装但未启用**——在 `requirements.txt` 里，但 settings.py 没配 `DEFAULT_AUTHENTICATION_CLASSES`。要加认证时再接。
- **motion-v 语法**：用 `<Motion as="div" :initial="..." :animate="..." :transition="...">`；SVG 用 `<Motion as="svg">`；React 版的 `motion.div` / `motion.svg` 这种写法在 Vue 里会报错。
- **主题系统**：`style.css` 里 CSS 变量 + `.dark` 类切换。任何要用主题的组件必须在 `<AppLayout>` 下面，通过 `useTheme()` 拿到 `theme` / `toggleTheme`。
- **平台范围**：只做性能压测调度。前端 tabs 里的 "UI 板块 / 接口板块" 是 figma 设计留的占位壳，**不要去做它们**。
- **跨平台开发**：项目同时支持 Mac 和 Windows。venv 路径不同：**Mac/Linux** 是 `backend/venv/bin/python`，**Windows** 是 `backend/venv/Scripts/python.exe`（注意是 `Scripts` 不是 `bin`）。所有命令在 §4、§9 双形态给出。**Mac 上 JMeter 需要 Java 17**，`./start.sh` 自动把 `/opt/homebrew/opt/openjdk@17/bin` 加到 PATH。
- **端口**：前端 5173（Vite），后端 8000（Django）。5173 被占时 Vite 自动挪到 5174/5175。
- **JMX 编辑 = L1**：只碰 `ThreadGroup` 的 `num_threads` / `ramp_time` / `duration`（`patch_jmx`，Step 2 v1.1 用）、所有组件的 `enabled`（`toggle_component`）、`testname`（`rename_component`），以及 8 种可编辑组件的业务字段（`update_component_detail`）。用 `lxml` **patch-in-place**，不要"前端 JSON → 后端重建 JMX"。
- **BackendListener 处理约定**：原 JMX 里的 BackendListener 在 `GET /components/` API 被 `_filter_tree_dicts` 过滤，前端看不到也摸不着。Admin 用 `BackendListenerConfig`（singleton pk=1）全局配置；`build_run_xml` 的 Step 4 按 `enabled + influxdb_url` 决定是否注入。**前端无需感知**。
- **JmxComponent.kind 字段**：前端应优先用 `kind` 判断组件类型，而非 `tag`。`ConfigTestElement` 当 guiclass=`HttpDefaultsGui` 时 kind=`'HttpDefaults'`，否则 kind==tag。
- **Step 2 存储模型 = 单文件 + 内存生成**（2026-04-28 改造）：磁盘只存原件 `<title>.jmx`（Step 1 编辑直写），Step 2 配置只入 DB（`thread_groups_config` JSON + `csv_bindings` 关联表 + `environment` FK）。validate / Step 3 跑压测时 `services/jmx.py::build_run_xml(task, inject_environment_dns=...)` 读原件 → 内存中链式 patch（替换 TG + patch CSVDataSet filename + 可选注入 DNSCacheManager）→ 返回 bytes。**不再有 `_run.jmx` 物理文件**——这样 Step 1 后续改动自动反映到下次 run，不存在"派生品过期"。
- **JMX 宽容解析**：`parse_jmx` 找不到 ThreadGroup 或是插件型（`UltimateThreadGroup` 等）时**不拒绝上传**，用默认值 10/0/60 兜底；但 `patch_jmx` 仍然严格（改不了插件型 TG 的属性就报错）——这是预期行为。
- **JMX 路径固定项目内**：所有上传的 .jmx 落在 `backend/jmeter/apache-jmeter-<VERSION>/scripts/`，代码**不读 `JMETER_HOME` env**。Docker 部署时在镜像里解压到 `/app/backend/jmeter/apache-jmeter-<VERSION>/` 同路径对齐，详情见 `backend/CLAUDE.md §18.3`。
- **软删除语义**：`DELETE /api/performance/tasks/:id/` 只在 DB 标记 `is_deleted=True` + 物理删原件 .jmx + 全部 csv_bindings + 物理 CSV；TaskCsvBinding 行 cascade 删；TaskRun / MetricSample 行通过 FK 保留。Admin 用 `Task.all_objects` 看全量。想真删用 `instance.hard_delete()`（API 没暴露）。
- **重新上传语义**（2026-04-28）：`POST /api/performance/tasks/:id/replace-jmx/` 覆盖原件 + **自动清空 `thread_groups_config` + 解绑全部 CSV + 删物理 CSV**。前端按钮在已配置 Step 2 时弹 confirm 提醒。
- **CSV 存储位置 = JMX 同目录**（scripts/）：每条 `TaskCsvBinding(component_path, filename)` 只存 bare 文件名，物理文件和 .jmx 同在 `backend/jmeter/apache-jmeter-<VERSION>/scripts/` 下。命名 `<jmx_stem>__<safe_path>.csv`（冲突追加 `_2`），其中 `<safe_path>` 是组件 path 把 `.` 换成 `_`（例如 `0.0.3` → `0_0_3`）。`build_run_xml` 把每个绑定的 CSVDataSet `filename` patch 成绝对路径，确保 JMeter 找得到。
- **磁盘空间检查 + fsync**：`services/jmeter.py::write_script` / `write_csv` 写盘前 `shutil.disk_usage()` 检查 < 100 MB 抛 `DiskFullError`（views 转 503），写盘走 `_atomic_write_bytes` (open + write + flush + fsync)。新建 `get_runs_dir()` 返回 `<jmeter_home>/runs/`，v1.1 跑 JMeter 用。
- **`TypeScript 6` + `erasableSyntaxOnly`**：前端不能用 constructor parameter properties（`constructor(public foo: string)` 这种语法），要写成先声明 field 再在 constructor 里赋值。见 `frontend/src/lib/api.ts` 的 `ApiError` 类。
- **v1.2 多机调度走分支判断**：`executor._select_load_generators()` 拉 `TaskRun.load_generators` M2M（前端 StartRunModal 选定后 `tasks/:id/run/` body 传 `load_generator_ids` 写入）；非空 → `_run_distributed`，空 + `LOCAL_FALLBACK=1` → 原 v1.1 单机流程。前端**必走 StartRunModal 选机器**，再调 startRun（即使只选 1 台）。
- **agent ↔ 主控通信**：agent 在容器里用 `host.docker.internal:8000`（macOS Docker Desktop 内置；Linux 走 `extra_hosts: host-gateway`）回调主控；主控调 agent 用 `LoadGenerator.base_url`（`http://<ip>:<port>`）。Bearer 鉴权 = `settings.FALCON_AGENT_TOKEN`，空 token 不强校验（开发态）。
- **多机 InfluxDB 切分**：分布式时 `build_shard_jmx` 给每片注入 `host=pod_name` tag。后端 InfluxDB 数据完备（已验证 shard_count + 3 个 host tag + 每 host samples 均衡）；前端按 host 切线 UI（dashboard/`TrendsTab` 等）后端数据 OK 但前端展示未现场看。
- **agent 自注册不等同于在线可用**：scale-up 拉副本后 agent 还要 5–15s 才会调 `register/`；前端 StartRunModal 用 `loadGeneratorsApi.list()` 轮询刷新，不要在 scale-up 后立即起 run。
- **idle agent 释放策略**：30 min 无心跳 + status=idle → `release_idle_agents` 命令（cron 每 5 min 跑）调 scale_down 回收容器并标 LOST；lost 后心跳恢复会自动复活回 idle。

## 8. 用户信息

- 自述"新手全栈"，写代码偏 Python，前端不太熟；**用中文沟通**。
- 偏好有主见的默认值（比如 Django over Flask、SQLite 先跑通再说），不喜欢被问太多。
- 要求"不做就不做"——当他说"其他的不要做"，就严格守住范围，不要多加不必要的功能、抽象或错误处理。

## 9. 常用命令备忘

```bash
# 一键启停
./start.sh / ./stop.sh   # Mac
./start.bat / ./stop.bat # Windows（双击）

# 前端（跨平台）
cd frontend && npm run dev
cd frontend && npm run build
cd frontend && npx vue-tsc --noEmit
```

**后端（在 `backend/` 下）**

```bash
# Mac / Linux
./venv/bin/python manage.py runserver
./venv/bin/python manage.py migrate
./venv/bin/python manage.py makemigrations
./venv/bin/python manage.py shell
./venv/bin/python manage.py setup_jmeter
./venv/bin/python manage.py setup_influxdb     # Step 3：建 InfluxDB 库 + 保留策略
./venv/bin/pip install -r requirements.txt
./venv/bin/pip freeze > requirements.txt

# 清掉所有测试 Task（含软删）+ 物理脚本（Mac）
./venv/bin/python manage.py shell -c "from performance.models import Task; [t.hard_delete() for t in Task.all_objects.all()]"

# Step 3: 启停 InfluxDB（每台开发机一次性配置）
docker compose -f backend/docker-compose.dev.yml up -d
docker compose -f backend/docker-compose.dev.yml down       # 停
docker compose -f backend/docker-compose.dev.yml down -v    # 停并清数据

# v1.2: falcon-agent 容器化压力源（compose 已固化 3 个 service: agent1/agent2/agent3）
docker compose -f backend/docker-compose.dev.yml build agent1              # 构建镜像（3 个 service 共享镜像，build 任意一个即可）
docker compose -f backend/docker-compose.dev.yml up -d agent1 agent2 agent3 # 起 3 台
docker compose -f backend/docker-compose.dev.yml up -d agent1              # 只起 1 台
docker compose -f backend/docker-compose.dev.yml down agent1 agent2 agent3 # 全停
./start.sh                                                                  # 已带 release_idle_agents 后台周期（每 5 min）
./venv/bin/python manage.py release_idle_agents                            # 手动跑一次回收
./venv/bin/python manage.py release_idle_agents --dry-run --minutes 5      # 调试用
```

```bash
# Windows
./venv/Scripts/python.exe manage.py runserver
./venv/Scripts/python.exe manage.py migrate
./venv/Scripts/python.exe manage.py makemigrations
./venv/Scripts/python.exe manage.py shell
./venv/Scripts/python.exe manage.py setup_jmeter
./venv/Scripts/pip.exe install -r requirements.txt
./venv/Scripts/pip.exe freeze > requirements.txt

# 清掉所有测试 Task（Win）
./venv/Scripts/python.exe manage.py shell -c "from performance.models import Task; [t.hard_delete() for t in Task.all_objects.all()]"
```

## 10. 换机迁移 / 多电脑同步

**OneDrive 上**（`~/Documents/OneDrive/FalconSync/claude-memory/`）：装着老电脑的历史对话 jsonl + memory/ markdown。

**当前同步策略 = 仅迁移记忆**（用户 2026-04-27 选择方案 B）：
- 新机首次配置时，把 OneDrive 的 `memory/MEMORY.md` + `*.md` **手动拷到** `~/.claude/projects/-Users-falcon-Documents-Falcon/memory/`
- 不做软链方案 → 多台机器记忆**不互通**（每台机器独立演化）
- 历史对话 jsonl 不拷（占空间且当前会话用不到）
- 未来若想做实时跨机同步，可以改回软链方案：删掉本地 `~/.claude/projects/-Users-falcon-Documents-Falcon/`，再 `ln -s ~/Documents/OneDrive/FalconSync/claude-memory <同名路径>`

**不同步的内容**（每台机器独立）：
- 后端：`backend/venv/`、`backend/db.sqlite3`、`backend/.env`、`backend/jmeter/apache-jmeter-*/`、`backend/media/`
- 前端：`frontend/node_modules/`
- Claude：项目级 `Falcon/.claude/`、全局 `~/.claude/settings.json` 等

**新 Mac 首次配置**（项目放 `~/Documents/Falcon`）：

```bash
# 0. 一次性装工具
brew install git python@3.12 openjdk@17 node
npm i -g @anthropic-ai/claude-code

# 1. clone 项目
cd ~/Documents && git clone https://github.com/jiuwumyself/Falcon.git Falcon
cd Falcon

# 2. （可选）从 OneDrive 拷记忆过来
mkdir -p ~/.claude/projects/-Users-falcon-Documents-Falcon/memory
cp ~/Documents/OneDrive/FalconSync/claude-memory/memory/*.md \
   ~/.claude/projects/-Users-falcon-Documents-Falcon/memory/

# 3. 后端
cd backend
python3.12 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
cp .env.example .env
echo 'JMETER_VERSION=5.6.3' >> .env
./venv/bin/python manage.py migrate           # 新建空 SQLite
./venv/bin/python manage.py setup_jmeter      # 自动下 JMeter + 插件 (~80MB)

# 4. 前端
cd ../frontend && npm install

# 5. 启动
cd .. && ./start.sh            # 一键，Ctrl+C 停止
```

**Mac vs Win 速查**：

| 操作 | Win | Mac |
|---|---|---|
| Python 可执行 | `./venv/Scripts/python.exe` | `./venv/bin/python` |
| pip 可执行 | `./venv/Scripts/pip.exe` | `./venv/bin/pip` |
| 杀 8000 / 5173 | `stop.bat` | `lsof -ti:8000,5173 \| xargs kill -9` |
| Claude 记忆目录名 | `C--Users-admin-Desktop-MyProject-Coder-Falcon` | `-Users-Falcon-Documents-Falcon` |
