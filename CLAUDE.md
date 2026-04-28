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
│   │   │   └── validator.py     ★ 1 并发校验（HeaderManager/CSV 作用域、变量替换）
│   │   ├── management/commands/
│   │   │   └── setup_jmeter.py  手动预装 JMeter（或首次上传时自动下载）
│   │   ├── tests/fixtures/      sample.jmx（parse/patch 测试用）
│   │   └── migrations/0001_initial.py
│   ├── jmeter/           **JMeter 工具 + 脚本存储**（apache-jmeter-5.6.3/ gitignored）
│   │   └── apache-jmeter-5.6.3/scripts/   ★ 所有上传的 .jmx 物理存放在这里
│   ├── media/            只存 CSV 了（jmx 走 jmeter/scripts，整个 media/ gitignored）
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
│   │   │   │   ├── ConfigStage.vue         Step 2 根组件（TG 切换器 + 场景 tabs + 左参数/右图 + 校验结果）
│   │   │   │   ├── configStageCtx.ts       6 个场景定义（SCENARIOS 数组：id / label / color / icon / kind / defaultParams）
│   │   │   │   └── config/                 Step 2 子组件：ScenarioTabs / ThreadGroupPicker / TgParamsForm / ThreadGroupChart（echarts）/ EnvironmentPicker / ValidateResultTable
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

**v1 已落地**（最近一次更新 2026-04-28，分支 `feat/step1-step2-polish`）：

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
  - `GET /api/performance/tasks/:id/components/` → 组件树（JmxComponent[]，嵌套 children）
  - `POST /api/performance/tasks/:id/components/toggle/` body `{path, enabled}` → 切换单个组件 enabled
  - `POST /api/performance/tasks/:id/components/rename/` body `{path, testname}` → 改 testname
  - `GET /api/performance/tasks/:id/components/detail/?path=...` → HTTPSampler / HeaderManager 字段
  - `PATCH /api/performance/tasks/:id/components/detail/` body `{path, kind, fields}` → 写回字段
  - `POST /api/performance/tasks/:id/components/upload-csv/`（multipart，body `path` + `csv_file`）→ **按 CSVDataSet 的组件 path 绑定** CSV，落盘命名 `<jmx_stem>__<safe_path>.csv`，写 / 更新 `TaskCsvBinding`
  - `POST /api/performance/tasks/:id/components/delete-csv/` body `{path}` → 解除某 CSVDataSet 的绑定（删行 + 删物理文件）
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
  - **单文件模型**：磁盘只存原件 `<title>.jmx`。跑压测前一秒 `services/jmx.py::build_run_xml(task)` 内存里读原件 → 套 thread_groups_config → 套 csv_bindings 的绝对路径 → （v1.1 执行时）注入 `DNSCacheManager`。validate / 未来 run 都吃这份内存 XML
  - **多 TG 独立配置**：每个启用的 TG 单独存 `{path, scenario, kind, params}`；前端 TG 切换器让用户逐个配；禁用的 TG 不显示、保存时原样保留
  - **插件自动下载**：`setup_jmeter` 命令装 `jmeter-plugins-casutg` + `cmn-jmeter` 到 `lib/ext/`（Maven Central）。Ultimate/Arrivals 依赖这俩 JAR
  - **1 并发校验**：`performance/services/validator.py` 用 Python `requests` 模拟；按 JMeter 作用域规则合并 HeaderManager + CSVDataSet 变量；Environment 的 hosts 映射通过 IP 直连 + Host 头实现
  - **CSV 变量替换**：validator 读作用域内 CSVDataSet 的第一行，按 `variableNames` 建字典替换 Sampler 里的 `${name}`；未解析的 `${}` 保留字面串 + `unresolved_vars` 回给前端展示警告
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
  - **Step 1 上传脚本**：未上传 → dropzone（自动触发 POST `/tasks/`，title 直接用文件名，**不再加日期前缀**）；已上传 → 头部 + `ScriptTree`（组件树 + enabled toggle + 双击改名 + HTTPSampler/HeaderManager 抽屉编辑 + CSVDataSet 行内 Paperclip 上传）。重新上传按钮：**已配置 Step 2 时弹 confirm 提醒清空**，上传后 toast 反馈
  - **Step 2 任务配置** = 场景 tab + 参数表单 + echarts 预览 + 1 并发校验。每个场景 pill 旁有 `?` 图标 hover tooltip（用途 / 典型参数 / 关注指标）。多 TG 时顶部 TG 切换器，逐个配
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

1. **JMeter CLI 执行**（v1.1 主菜，Step 3）：
   - 新增 `performance/services/executor.py`，用 `subprocess.Popen` 调 `jmeter -n -t <run.jmx> -l <results.jtl> -e -o <report-dir>`
   - run.jmx 由 `build_run_xml(task, inject_environment_dns=True)` 写到 `<jmeter_home>/runs/<run_id>/run.jmx`，跑完保留作"本次实际跑的脚本快照"
   - 触发：`POST /api/performance/tasks/:id/run` → 创建 `TaskRun(status=running)` + 启子进程；`POST /tasks/:id/runs/:run_id/cancel` → kill 子进程
   - 跑完：解析 `.jtl`（`csv` 模块读最后一遍）→ 填 `avg_rps` / `p99_ms` / `error_rate` / `total_requests` → `status=success/fail`
   - 前端 Step 3：状态机视图（待运行 / 运行中带秒数计时 / 成功 / 失败）+ 取消按钮 + 实时 RPS / P99 / 错误率折线（轮询 `runs/:id/metrics?since=<ts>`）
2. **压力机管理**（v1.1 Step 3 配套）：v1 单机本地跑（master = web 进程同主机）；v1.2 加 `LoadGenerator` 模型（host / port / capacity）+ 远程 JMeter slave（`-R <host:port>`）选择
3. **异步化**：Celery + Redis（同步 subprocess 会卡死 gunicorn worker；v1 dev 阶段可先用 Python `threading.Thread` 跑通，v1.1 再升级）
4. **时序采样**：Celery 任务里 tail `.jtl` 增量行，每秒汇总写 `MetricSample`；前端 `ChronosNerve`/`MetricsColumn` 图表此时才接真数据
5. **报告 / AI 分析**（v1.2+）：Task 选定 service → 跑完拉 Grafana / Pinpoint / Arthus 数据 → 多 run 对比 → AI 文字总结 → 导出 Word；服务未接入时退化为"仅 JTL 总结 + 监控接入提示"

## 7. 关键约定 & 踩坑点

- **`figma/` 是设计源，不是运行时代码**。frontend 里**不要 import 它**。需要 UI 参考时读它、照着写 Vue 版本。
- **没有鉴权**。路由没 guard，后端 `DEFAULT_PERMISSION_CLASSES = [AllowAny]`。user 明确要求"先不做登录验证"。
- **`djangorestframework-simplejwt` 已装但未启用**——在 `requirements.txt` 里，但 settings.py 没配 `DEFAULT_AUTHENTICATION_CLASSES`。要加认证时再接。
- **motion-v 语法**：用 `<Motion as="div" :initial="..." :animate="..." :transition="...">`；SVG 用 `<Motion as="svg">`；React 版的 `motion.div` / `motion.svg` 这种写法在 Vue 里会报错。
- **主题系统**：`style.css` 里 CSS 变量 + `.dark` 类切换。任何要用主题的组件必须在 `<AppLayout>` 下面，通过 `useTheme()` 拿到 `theme` / `toggleTheme`。
- **平台范围**：只做性能压测调度。前端 tabs 里的 "UI 板块 / 接口板块" 是 figma 设计留的占位壳，**不要去做它们**。
- **跨平台开发**：项目同时支持 Mac 和 Windows。venv 路径不同：**Mac/Linux** 是 `backend/venv/bin/python`，**Windows** 是 `backend/venv/Scripts/python.exe`（注意是 `Scripts` 不是 `bin`）。所有命令在 §4、§9 双形态给出。**Mac 上 JMeter 需要 Java 17**，`./start.sh` 自动把 `/opt/homebrew/opt/openjdk@17/bin` 加到 PATH。
- **端口**：前端 5173（Vite），后端 8000（Django）。5173 被占时 Vite 自动挪到 5174/5175。
- **JMX 编辑 = L1**：只碰 `ThreadGroup` 的 `num_threads` / `ramp_time` / `duration`（由 `patch_jmx` 负责，Step 2 v1.1 用），以及所有组件的 `enabled` 属性（由 `toggle_component` 负责，Step 1 当前就用）。其他元素（Samplers、Assertions、Listeners、BeanShell…）一律原样保留。用 `lxml` **patch-in-place**，不要"前端 JSON → 后端重建 JMX"。
- **Step 2 存储模型 = 单文件 + 内存生成**（2026-04-28 改造）：磁盘只存原件 `<title>.jmx`（Step 1 编辑直写），Step 2 配置只入 DB（`thread_groups_config` JSON + `csv_bindings` 关联表 + `environment` FK）。validate / Step 3 跑压测时 `services/jmx.py::build_run_xml(task, inject_environment_dns=...)` 读原件 → 内存中链式 patch（替换 TG + patch CSVDataSet filename + 可选注入 DNSCacheManager）→ 返回 bytes。**不再有 `_run.jmx` 物理文件**——这样 Step 1 后续改动自动反映到下次 run，不存在"派生品过期"。
- **JMX 宽容解析**：`parse_jmx` 找不到 ThreadGroup 或是插件型（`UltimateThreadGroup` 等）时**不拒绝上传**，用默认值 10/0/60 兜底；但 `patch_jmx` 仍然严格（改不了插件型 TG 的属性就报错）——这是预期行为。
- **JMX 路径固定项目内**：所有上传的 .jmx 落在 `backend/jmeter/apache-jmeter-<VERSION>/scripts/`，代码**不读 `JMETER_HOME` env**。Docker 部署时在镜像里解压到 `/app/backend/jmeter/apache-jmeter-<VERSION>/` 同路径对齐，详情见 `backend/CLAUDE.md §18.3`。
- **软删除语义**：`DELETE /api/performance/tasks/:id/` 只在 DB 标记 `is_deleted=True` + 物理删原件 .jmx + 全部 csv_bindings + 物理 CSV；TaskCsvBinding 行 cascade 删；TaskRun / MetricSample 行通过 FK 保留。Admin 用 `Task.all_objects` 看全量。想真删用 `instance.hard_delete()`（API 没暴露）。
- **重新上传语义**（2026-04-28）：`POST /api/performance/tasks/:id/replace-jmx/` 覆盖原件 + **自动清空 `thread_groups_config` + 解绑全部 CSV + 删物理 CSV**。前端按钮在已配置 Step 2 时弹 confirm 提醒。
- **CSV 存储位置 = JMX 同目录**（scripts/）：每条 `TaskCsvBinding(component_path, filename)` 只存 bare 文件名，物理文件和 .jmx 同在 `backend/jmeter/apache-jmeter-<VERSION>/scripts/` 下。命名 `<jmx_stem>__<safe_path>.csv`（冲突追加 `_2`），其中 `<safe_path>` 是组件 path 把 `.` 换成 `_`（例如 `0.0.3` → `0_0_3`）。`build_run_xml` 把每个绑定的 CSVDataSet `filename` patch 成绝对路径，确保 JMeter 找得到。
- **磁盘空间检查 + fsync**：`services/jmeter.py::write_script` / `write_csv` 写盘前 `shutil.disk_usage()` 检查 < 100 MB 抛 `DiskFullError`（views 转 503），写盘走 `_atomic_write_bytes` (open + write + flush + fsync)。新建 `get_runs_dir()` 返回 `<jmeter_home>/runs/`，v1.1 跑 JMeter 用。
- **`TypeScript 6` + `erasableSyntaxOnly`**：前端不能用 constructor parameter properties（`constructor(public foo: string)` 这种语法），要写成先声明 field 再在 constructor 里赋值。见 `frontend/src/lib/api.ts` 的 `ApiError` 类。

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
./venv/bin/pip install -r requirements.txt
./venv/bin/pip freeze > requirements.txt

# 清掉所有测试 Task（含软删）+ 物理脚本（Mac）
./venv/bin/python manage.py shell -c "from performance.models import Task; [t.hard_delete() for t in Task.all_objects.all()]"
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
