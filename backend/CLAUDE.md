# Falcon 后端上下文

> 根目录 `CLAUDE.md` 已覆盖整体项目信息。本文件只写**后端子项目专属的约定、细节和踩坑点**。

## 1. 技术栈要点

- **Python 3.12**（venv 在 `backend/venv/`）
- **Django 5.1** + **djangorestframework 3.15**
- **lxml 6.x**（处理 JMX XML 的核心依赖）
- **django-cors-headers**（放行前端 `localhost:5173`）
- **python-dotenv**（加载 `.env`）
- **psycopg 3.2**（已装，默认不用；`DB_ENGINE=postgres` 时切换到 PostgreSQL）
- **djangorestframework-simplejwt 5.3**（已装但**未启用**；平台暂不做认证）
- **将来要装**：`celery`、`redis`（v1.1 接 JMeter CLI 执行那一步再装）

## 2. 目录结构

```
backend/
├── config/                 Django "project" 包（不是业务 app）
│   ├── settings.py         INSTALLED_APPS + MEDIA + REST_FRAMEWORK + DB 切换逻辑
│   ├── urls.py             根路由：挂 /api/ → tasks.urls，DEBUG 时暴露 /media/
│   ├── wsgi.py / asgi.py
│   └── __init__.py
├── performance/            ✅ v1 已建好的业务 app（压测领域；原名 tasks，2026-04-23 按板块拆分重命名）
│   ├── apps.py
│   ├── models.py           Task / TaskRun / MetricSample / Environment / BackendListenerConfig 五张表
│   ├── serializers.py      Task / TaskRun / MetricSample / Environment Serializer
│   ├── views.py            TaskViewSet + EnvironmentViewSet
│   ├── urls.py             DefaultRouter 注册两个 ViewSet（URL 前缀 `/api/performance/`）
│   ├── admin.py            四张表都用 @admin.register 装饰器注册
│   ├── services/
│   │   ├── __init__.py
│   │   ├── jmeter.py       ★ JMeter 工具 + 插件下载 + 脚本文件存储
│   │   ├── jmx.py          ★ parse_jmx / patch_jmx / list_components / toggle_component /
│   │   │                   ★ list_thread_groups / replace_thread_group（lxml 实现）
│   │   ├── jmeter_runner.py ★ JMeter 子进程 + JTL 解析（校验 + 跑压测共用）
│   │   └── validator.py    ★ Step 2 校验：build_validate_xml → run_jmeter -n → JTL → ValidateResult
│   ├── management/commands/setup_jmeter.py   JMeter + 插件一键安装
│   ├── tests/
│   │   ├── __init__.py
│   │   └── fixtures/sample.jmx    有 ThreadGroup + CSVDataSet + HTTPSampler 的最小 JMX
│   └── migrations/         0001~0004（历史）/ 0005_backend_listener_config（2026-04-29）
├── media/                  上传文件：jmx/<task_id>/*.jmx、csv/<task_id>/*.csv（gitignored）
├── manage.py
├── db.sqlite3              默认数据库（gitignored）
├── .env                    本地环境变量（gitignored，不要提交）
├── .env.example            模板（已提交）
├── requirements.txt
└── venv/                   Python 虚拟环境（gitignored）
```

**约定**：`config/` **只放项目级配置**（settings、urls、wsgi），**不要往里塞 models / views**。所有业务代码一定要在 app 里（比如 `tasks/`）。

## 3. 运行命令（跨平台注意事项）

venv 路径按平台不同：**Mac/Linux** 是 `bin/`，**Windows** 是 `Scripts/`。直接用绝对路径调，比 activate 更稳。

```bash
# Mac / Linux (在 backend/ 下)
./venv/bin/python manage.py runserver           # 默认 http://localhost:8000
./venv/bin/python manage.py migrate
./venv/bin/python manage.py makemigrations
./venv/bin/python manage.py makemigrations <app_name>
./venv/bin/python manage.py shell
./venv/bin/python manage.py createsuperuser
./venv/bin/python manage.py check
./venv/bin/python manage.py startapp <app_name>
./venv/bin/python manage.py test

./venv/bin/pip install -r requirements.txt
./venv/bin/pip install <pkg>
./venv/bin/pip freeze > requirements.txt
```

```bash
# Windows (在 backend/ 下)
./venv/Scripts/python.exe manage.py runserver
./venv/Scripts/python.exe manage.py migrate
./venv/Scripts/python.exe manage.py makemigrations
# ... 其余命令同上，把 ./venv/bin/python 换成 ./venv/Scripts/python.exe，
#     ./venv/bin/pip 换成 ./venv/Scripts/pip.exe

./venv/Scripts/pip.exe install -r requirements.txt
```

**不要用** `python manage.py ...`（系统 Python 可能不是 3.12，也没装依赖）。**激活 venv** 也不推荐——直接绝对路径调最稳。

## 4. 环境变量 & 配置

`settings.py` 用 `python-dotenv` 在启动时加载 `backend/.env`。**所有可变配置都走环境变量**，不要硬编码：

```python
# settings.py 的模式
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '<dev fallback>')
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
```

改配置的正确方式：
1. 在 `.env.example` 里加一行注释好的变量（提交）
2. 在自己的 `.env` 里设值（不提交）
3. 在 `settings.py` 里 `os.getenv('KEY', default)` 读取

## 5. 数据库切换

默认 SQLite，切 PostgreSQL 只要在 `.env` 设：

```bash
DB_ENGINE=postgres
DB_NAME=falcon
DB_USER=postgres
DB_PASSWORD=xxx
DB_HOST=localhost
DB_PORT=5432
```

`settings.py` 的 `DATABASES` 段已经按 `DB_ENGINE` 分支好了。切换后要记得跑 `migrate` 重建表。**SQLite 的 `db.sqlite3` 不会被迁移过去**，那是两套独立数据。

## 6. CORS

`settings.py` 里放行 `http://localhost:5173` / `http://127.0.0.1:5173`，让 Vite dev server 能调 Django。改 CORS 白名单：改 `.env` 的 `CORS_ALLOWED_ORIGINS`（逗号分隔）。

**不要** 用 `CORS_ALLOW_ALL_ORIGINS = True`，安全原因。

## 7. 当前业务进度

| 模块 | 状态 |
|---|---|
| 脚手架、settings.py、CORS、DB 配置 | ✅ |
| 初始 migrations（admin/auth/contenttypes/sessions） | ✅ |
| 业务 app `tasks/` | ✅ v1 完成 |
| 数据模型（Task / TaskRun / MetricSample）| ✅ |
| JMX 解析 / 补丁服务（`performance/services/jmx.py`，宽容解析） | ✅ |
| **组件树遍历 + enabled 切换**（`performance/services/jmx.py::list_components` / `toggle_component`） | ✅ |
| **JMeter 工具下载 + 脚本存储**（`performance/services/jmeter.py`） | ✅ |
| **软删除**（`is_deleted` + `deleted_at` + `TaskManager`） | ✅ |
| **任务 title 自动加日期前缀 `YYYY-MM-DD_`** | ✅ |
| DRF serializers / viewsets | ✅ |
| `/api/performance/tasks/` 路由挂载 | ✅ |
| CSV 附件上传 | ✅ |
| **管理命令 `setup_jmeter`**（预装 JMeter 5.4.1 + 插件 JAR） | ✅ |
| **Step 2 任务配置 = 线程组替换**（`list_thread_groups` / `replace_thread_group`，支持 **5 种** TG：标准 / Stepping / Concurrency / Ultimate / Arrivals）| ✅ |
| **CSV 作用域变量替换** | ✅ JMeter 自己处理（校验走 `jmeter -n` 真跑） |
| **Environment 模型**（name / is_default / host_entries JSONField）+ admin 编辑 | ✅ |
| **可执行 JMX = 内存生成**（`build_run_xml(task)` 不再写 `_run.jmx` 物理文件）| ✅（2026-04-28 取消派生）|
| **CSV 多绑定**（`TaskCsvBinding` 关联表，按 CSVDataSet 组件 path 独立挂 CSV）| ✅（2026-04-28）|
| **插件自动安装**（ensure_plugins_installed：jmeter-plugins-casutg + cmn-jmeter）| ✅ |
| **Step 2 校验 = 真 JMeter 跑（每接口 1 次）**（`services/jmx.py::build_validate_xml` + `services/jmeter_runner.py::run_jmeter` + `validator.py::validate_task`） | ✅ |
| 任务列表页（性能板块 ChronosNerve）+ 右键删除 | ✅ |
| **BackendListenerConfig 单例模型**（pk=1，admin 配置，build_run_xml 自动注入）| ✅（2026-04-29）|
| **组件树 BackendListener 过滤**（`_filter_tree_dicts`，前端不展示）| ✅（2026-04-29）|
| **JmxComponent.kind 字段**（ConfigTestElement+HttpDefaultsGui → 'HttpDefaults'，其余同 tag）| ✅（2026-04-29）|
| **8 种可编辑组件**（HTTPSampler/HeaderManager 原有 + HttpDefaults/JSONPathAssertion/BeanShell Pre+Post/RegexExtractor/JSONPathExtractor/CSVDataSet）| ✅（2026-04-29）|
| **BeanShell Pre JAR 上传**（`write_jar` → lib/ext/，全局共享；`POST upload-jar/`）| ✅（2026-04-29）|
| 压测执行引擎（调 JMeter CLI） | ❌ v1.1 |
| MetricSample 时序写入 | ❌ v1.1（表建了，暂无写入） |
| 异步调度（Celery + Redis） | ❌ v1.1 |
| 认证（JWT） | ❌ 故意不做 |
| Ultimate ThreadGroup 参数编辑 | ❌ v1：单行参数；多行（多峰错峰）v1.2+ |
| 集合点测试（Synchronizing Timer）模式预设 | ❌ v1.1 |
| Service / Grafana / Pinpoint / Arthus 接入 | ❌ v1.2+（Step 2 选 service → 跑完拉指标 → AI 报告对比）|

## 8. 已落地的业务模型（见 `performance/models.py`）

```
Environment (压测环境，hosts 映射等，Step 2 用)
Task (压测任务定义 + JMX 文件 + Step 2 配置 JSON + environment FK)
 ├─── TaskCsvBinding (按 CSVDataSet 组件 path 绑定 CSV，多个)
 └─── TaskRun (一次执行记录，v1.1 才会有数据)
       └─── MetricSample (时序采样点，v1.1 才会有数据)
BackendListenerConfig (singleton pk=1, admin 配置，build_run_xml 注入)
```

### `Environment`（Step 2 新增）
- `name`（unique）/ `description` / `is_default`
- `host_entries`（JSONField）：`[{"hostname": "api.foo.com", "ip": "10.0.0.1"}, ...]` —— 执行时注入 JMX 的 DNSCacheManager，不改远程机 hosts
- **创建/编辑走 Django admin**（`/admin/performance/environment/`）；前端只读
- Task 通过 FK `environment` 引用；Step 2 的"校验"和未来执行都拿它的 host_entries

### `Task`
- `title`、`description`、`biz_category`（TextChoices: shared/ai/kg）
- `jmx_filename`（CharField，bare 文件名）—— **原件**物理文件在 `<JMETER_HOME>/scripts/<jmx_filename>`
- `jmx_hash`（sha256，去重）
- `csv_bindings` 反向关联 `TaskCsvBinding`（每个 CSVDataSet 一条；2026-04-28 取代旧 `csv_filename` 单字段）
- **JMX 解析字段**：`virtual_users`、`ramp_up_seconds`、`duration_seconds` — 这三个字段与 JMX 文件里的 `ThreadGroup` 内容**保持同步**；Step 2 保存时也会同步（用第一个启用的标准 TG 的参数）
- **Step 2 字段**：
  - `thread_groups_config`（JSONField，默认 `[]`）—— `[{"path":"0.0","scenario":"baseline","kind":"ThreadGroup","params":{...}}, ...]`
  - `environment`（FK → Environment, nullable）
  - **没有 `run_jmx_filename`**（2026-04-28 移除）：跑压测前 `services/jmx.py::build_run_xml(task)` 在内存生成可执行 XML，不写盘。状态由 serializer 计算字段 `status` 给前端：空配置 → `draft`，非空 → `configured`
- `owner`（FK User，nullable）
- `is_deleted` / `deleted_at`（软删除标记）
- `created_at` / `updated_at`
- **Manager**：`Task.objects`（默认，过滤掉软删）/ `Task.all_objects`（全量，admin 用）
- **方法**：`delete()` 软删 + 物理删 .jmx + 删全部 csv_bindings（含物理 CSV）；`hard_delete()` 真·删行；`jmx_path()` + `read_jmx_bytes()` / `write_jmx_bytes()` 一组读写 API

### `TaskCsvBinding`（2026-04-28 新增）
按 CSVDataSet 组件 path 绑定 CSV 文件。一个 Task 可有多条。
- `task` FK（cascade 删）
- `component_path`（如 `"0.0.3"`）+ `filename` —— 唯一约束 `(task, component_path)`
- 物理 CSV 在 `<JMETER_HOME>/scripts/<jmx_stem>__<safe_path>.csv`（path 的 `.` 换成 `_`）
- `build_run_xml` 把 CSVDataSet 的 `filename` 字段 patch 成绝对路径，确保 JMeter 找得到（无论"全局"还是"局部" CSVDataSet——位置不动，只改 filename）

### `TaskRun`
- `task` FK、`status`（pending/running/success/fail/cancelled）
- `started_at` / `finished_at`
- **执行参数快照**：`virtual_users` / `ramp_up_seconds` / `duration_seconds`（Task 以后改了，历史 run 还知道当时跑的啥）
- **汇总指标**：`total_requests`、`avg_rps`、`p99_ms`、`error_rate`（0-100）、`error_message`

### `MetricSample`
- `run` FK、`timestamp`、`rps`、`p99_ms`、`error_rate`、`active_users`
- 索引 `(run, timestamp)`

## 9. Django App 的约定

每个业务 app 标准结构：

```
tasks/
├── __init__.py
├── apps.py
├── models.py           数据模型
├── admin.py            Django Admin 注册
├── serializers.py      DRF 序列化（手动建，startapp 不给）
├── views.py            DRF ViewSet
├── urls.py             app 级路由（手动建）
├── migrations/         自动生成，不要手改
└── tests.py
```

新建 app 的完整流程（命令省略 `./venv/bin/python`（Mac/Linux）或 `./venv/Scripts/python.exe`（Win）前缀）：
1. `manage.py startapp <name>`
2. 在 `config/settings.py` 的 `INSTALLED_APPS` 追加 `'<name>'`
3. 写 `models.py`
4. `manage.py makemigrations <name>`
5. `manage.py migrate`
6. 写 `admin.py`（可视化调试超方便）
7. 写 `serializers.py` + `views.py`
8. 在 `<name>/urls.py` 建 app 级路由，在 `config/urls.py` `include()` 它

## 10. DRF 约定

- **URL 前缀统一 `/api/`**（前端 Vite 代理的是这个前缀）
- 用 `ModelViewSet` + `DefaultRouter`，不要手写一堆 `APIView`
- `settings.py` 已配：`PAGE_SIZE=50`、`DEFAULT_PERMISSION_CLASSES=[AllowAny]`
- **暂时** 全部 `AllowAny`（平台没认证）；后续接 auth 时统一改 settings

### 已暴露的 `/api/performance/tasks/` 端点

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/performance/tasks/` | 上传 JMX（multipart）→ 校验 .jmx 后缀 + 大小 ≤ 10MB → 后端解析字段 → 创建 Task |
| `GET` | `/api/performance/tasks/` | 分页列表 |
| `GET` | `/api/performance/tasks/:id/` | 详情 |
| `PATCH` | `/api/performance/tasks/:id/` | 改标题/描述/分类/vuser/ramp/duration；后三个改了会同步 patch 到 JMX 文件（v1 前端已不调，留给 v1.1 Step 2） |
| `DELETE` | `/api/performance/tasks/:id/` | **软删除**：`is_deleted=True` + 物理删除 scripts/ 下的 .jmx（TaskRun/MetricSample 保留） |
| `POST` | `/api/performance/tasks/:id/replace-jmx/` | 覆盖同一任务的 JMX（multipart，字段名 `jmx_file`）；保留 title/biz/description/created_at；**自动清空 `thread_groups_config` + 解绑全部 csv_bindings + 删物理 CSV**；磁盘文件名不变 |
| `GET` | `/api/performance/tasks/:id/raw-xml/` | 返回 `{ xml: "..." }`（原件） |
| `GET` | `/api/performance/tasks/:id/download/` | 二进制 JMX 下载（原件） |
| `GET` | `/api/performance/tasks/:id/preview-run-xml/` | 返回 `{ xml }`（内存中由 `build_run_xml(task)` 组装的可执行版，调试 / 用户预览用，不写盘） |
| `GET` | `/api/performance/tasks/:id/components/` | 组件树 `[JmxComponent]`（每项 `path/tag/kind/testname/enabled/children`；**BackendListener 节点自动过滤不返回**） |
| `POST` | `/api/performance/tasks/:id/components/toggle/` | body `{path, enabled}` → 定位组件改 `enabled` 属性，写盘，返回新树（已过滤） |
| `POST` | `/api/performance/tasks/:id/components/rename/` | body `{path, testname}` → 定位组件改 `testname` 属性（允许空串），写盘，返回新树（已过滤） |
| `GET` | `/api/performance/tasks/:id/components/detail/?path=...` | 返回可编辑组件的字段结构。支持 8 种 kind：HTTPSamplerProxy / HeaderManager / HttpDefaults / JSONPathAssertion / BeanShellPreProcessor / BeanShellPostProcessor / RegexExtractor / JSONPathExtractor / CSVDataSet（**CSVDataSet 不含 filename**）|
| `PATCH` | `/api/performance/tasks/:id/components/detail/` | body `{path, kind, fields}` → 按 kind 写回字段（同上 8 种），写盘，返回新树（已过滤）|
| `POST` | `/api/performance/tasks/:id/components/upload-csv/` | multipart `path` + `csv_file` → 落盘 + upsert `TaskCsvBinding`；返回更新后 Task |
| `POST` | `/api/performance/tasks/:id/components/delete-csv/` | body `{path}` → 删 binding + 物理 CSV；返回更新后 Task |
| `POST` | `/api/performance/tasks/:id/components/upload-jar/` | multipart `jar_file`（.jar ≤ 50MB）→ 写入 JMeter lib/ext/（全局共享）；返回 `{filename, message}`（含远程机手动安装提示）|
| `GET` | `/api/performance/tasks/:id/thread-groups/` | 返回 `{thread_groups:[{path,kind,tag,testname,enabled,current_params}], saved_config, environment}`；前端 Step 2 初始化用 |
| `PATCH` | `/api/performance/tasks/:id/thread-groups/` | body `{thread_groups:[{path,kind,params}], environment_id}`；**仅入库**（`thread_groups_config` + `environment`），不再写 `_run.jmx`；先 dry-run 一次 `replace_thread_group` 校验所有 path/kind/params 合法；Stepping/Concurrency/Ultimate/Arrivals 会按需调 `ensure_plugins_installed()` |
| `POST` | `/api/performance/tasks/:id/validate/` | body `{environment_id?}`；调 `validate_task(task)`：内存 build_validate_xml（所有启用 TG 降级为 1×1）→ subprocess `jmeter -n -t run.jmx -l result.jtl` → 解析 JTL → 返回 `[{path,testname,url,status,elapsed_ms,ok,error?}]`。冷启 3-5s；JMeter 失败时 500 + 日志尾巴 |
| `GET` | `/api/performance/environments/` | Environment 列表（不分页），前端 Step 2 下拉用 |
| `GET` | `/api/performance/environments/:id/` | Environment 详情 |

`TaskRun` / `MetricSample` v1 没暴露端点（还没数据）。`Environment` 创建/修改走 admin，不暴露 write 端点。

## 11. 迁移（migration）工作流

- **改了 models 必须跑 `makemigrations`**，否则改动不生效
- **迁移文件要提交** 到 git（`<app>/migrations/*.py`），跟代码绑定
- **不要手改 migrations 文件**（除非你知道自己在干什么）
- 在别人刚 pull 完你的改动后，他们要跑一次 `migrate` 同步
- 想查当前迁移状态：`manage.py showmigrations`

## 12. Django Admin

`/admin/` 是调试利器。

- 先 `createsuperuser` 建管理员
- 在每个 app 的 `admin.py` 用 `admin.site.register(MyModel)` 注册
- 复杂点用 `@admin.register(MyModel)` + `class MyModelAdmin(admin.ModelAdmin): list_display = [...]`
- **开发期**：把所有业务表都注册进 admin，可视化建测试数据；**上线前**看情况决定留几个

## 13. 约定 & 踩坑

### 13.1 venv 路径按平台不同
- **Mac/Linux**：`./venv/bin/python`、`./venv/bin/pip`
- **Windows**：`./venv/Scripts/python.exe`、`./venv/Scripts/pip.exe`

**推荐不 activate，直接绝对路径调**——省掉忘记激活导致调用错 Python 的坑。Mac 上还要保证 `python3.12` 是 Homebrew 装的（不是系统的 3.9），建 venv 时用 `/opt/homebrew/bin/python3.12 -m venv venv` 显式指定。

### 13.2 `.env` 不要提交
`.gitignore` 根目录已经配好了（`.env`、`.env.local`、`.env.*.local` 都忽略）。要改模板去 `.env.example`。

### 13.3 `djangorestframework-simplejwt` 装了但没启用
在 `requirements.txt` 里能看到，但 `settings.py` 的 `DEFAULT_AUTHENTICATION_CLASSES` 没配，`urls.py` 也没接 token 接口。**现在请不要"顺手"启用它**——用户明确要求"先不做登录验证"。

### 13.4 时区 & 语言
`TIME_ZONE = 'Asia/Shanghai'`、`LANGUAGE_CODE = 'zh-hans'`、`USE_TZ = True`。存数据库的是 UTC，读出来自动转 Asia/Shanghai。前端直接用 ISO 字符串就行。

### 13.5 SQLite 的限制
- 单写并发：压测平台将来多个 worker 同时写 `MetricSample` 会上锁
- 所以**真上量时要切 PostgreSQL**（psycopg 已装好，切换几乎无感）
- 现在开发阶段用 SQLite 完全没问题

### 13.6 `psycopg[binary]` vs `psycopg`
`requirements.txt` 装的是 `psycopg[binary]`——含预编译的 C 扩展，Windows 开发不用装编译工具。上线 Linux 服务器建议改成源码版 `psycopg[c]`，自己编译性能更好。

### 13.7 静态文件
现在没用到 `collectstatic`（Django Admin 的静态文件 `DEBUG=True` 时由 runserver 自动服务）。上线时才需要 `STATIC_ROOT` 和 `collectstatic`。

## 14. 常见调试姿势

下面用 Mac/Linux 的 `./venv/bin/python` 写法。Windows 把所有 `./venv/bin/python` 替换为 `./venv/Scripts/python.exe` 即可。

```bash
# 进 shell 直接操作 ORM
./venv/bin/python manage.py shell
>>> from performance.models import Task
>>> Task.objects.create(title='Test', target_url='https://example.com', ...)

# 看 SQL
./venv/bin/python manage.py sqlmigrate performance 0001

# 看路由
./venv/bin/python manage.py show_urls    # 需要装 django-extensions，或者
./venv/bin/python -c "from django.urls import get_resolver; [print(p) for p in get_resolver().reverse_dict]"

# 重置数据库（开发期用）
rm db.sqlite3
./venv/bin/python manage.py migrate
./venv/bin/python manage.py createsuperuser
```

### 10.1 .jmx 上传大小上限

硬上限 **10 MB**，三道防线（改上限统一改 `settings.MAX_UPLOAD_SIZE`，其他两项自动跟着走）：

1. `settings.MAX_UPLOAD_SIZE = 10 * 1024 * 1024` — 产品规则常量
2. `settings.DATA_UPLOAD_MAX_MEMORY_SIZE` / `FILE_UPLOAD_MAX_MEMORY_SIZE` — Django 在 middleware 层直接拒绝过大请求体（不会进 view）
3. `views.py::create` 里再用 `jmx_upload.size > settings.MAX_UPLOAD_SIZE` 拿到业务语义的 400 返回 `{'jmx_file': ['文件超过 10MB 上限']}`

前端 `TaskCreateWizard.handleFile` 也有同值校验，避免无谓上传。

## 15. JMX 服务（`performance/services/jmx.py`）的使用约定

四个纯函数，**不要**把业务逻辑塞进来：

```python
from performance.services.jmx import (
    parse_jmx, patch_jmx, list_components, toggle_component,
    JmxFields, JmxComponent, JmxParseError,
)

# 1) 上传时抽 L1 字段（vuser/ramp/duration/csv_paths）
fields: JmxFields = parse_jmx(xml_bytes)

# 2) Step 2 v1.1 改参数（前端 v1 已不用）
new_bytes: bytes = patch_jmx(
    xml_bytes,
    virtual_users=200,
    ramp_up_seconds=30,
    duration_seconds=120,
    csv_path='/media/csv/1/users.csv',   # 只改第一个 CSVDataSet
)

# 3) Step 1 组件树：按 <hashTree> 配对结构递归遍历
tree: list[JmxComponent] = list_components(xml_bytes)
# 每个 JmxComponent 有 path(索引路径如 "0.0.1") / tag / kind / testname / enabled / children
# kind 通常 = tag；ConfigTestElement+HttpDefaultsGui 时 kind='HttpDefaults'
# views.py 的 _filter_tree_dicts 会过滤掉 BackendListener（前端不展示）

# 4) Step 1 切换某个组件的 enabled 属性
new_bytes: bytes = toggle_component(xml_bytes, path="0.2.1", enabled=False)

# 5) Step 1 重命名组件（改 testname 属性）
new_bytes: bytes = rename_component(xml_bytes, path="0.2.1", testname="Login 接口")

# 6) Step 1 抽屉编辑（8 种 kind）
detail = get_component_detail(xml_bytes, path="0.0.1")
# 返回 {kind, ...字段}。kind 取值及字段（2026-04-29 扩展）：
#   HTTPSamplerProxy → {domain, port, protocol, method, path, bodyMode, params, body, files}
#   HeaderManager    → {headers: [{name,value},...]}
#   HttpDefaults     → {domain, port, protocol, path, contentEncoding, connectTimeout,
#                       responseTimeout, implementation, followRedirects, useKeepAlive}
#   JSONPathAssertion → {jsonPath, expectedValue, jsonValidation, expectNull, invert, isRegex}
#   BeanShellPreProcessor / BeanShellPostProcessor → {script, parameters, resetInterpreter}
#   RegexExtractor   → {refname, regex, template, default, matchNumber, useHeaders}
#   JSONPathExtractor → {varName, jsonpath, default, matchNo}
#   CSVDataSet       → {variableNames, delimiter, fileEncoding, ignoreFirstLine, quotedData,
#                       recycle, stopThread, shareMode}  ← 不含 filename（由 TaskCsvBinding 管）
new_bytes = update_component_detail(xml_bytes, path="0.0.1", kind='HTTPSamplerProxy',
                                    fields={
                                        'method': 'POST',
                                        'bodyMode': 'raw',
                                        'body': '{"u":"alice"}',
                                        'files': [{'path':'a.jpg','paramname':'f','mimetype':'image/jpeg'}],
                                    })

# 7) Step 2 列出所有 ThreadGroup（含标准 + 插件型）
tgs = list_thread_groups(xml_bytes)
# [{'path': '0.0', 'kind': 'ThreadGroup', 'tag': 'ThreadGroup',
#   'testname': '...', 'enabled': True,
#   'current_params': {'users': 10, 'ramp_up': 5, 'duration': 60}}, ...]

# 8) Step 2 替换某个 TG 为新类型（原地替换元素，保留 hashTree 子树）
new_bytes = replace_thread_group(xml_bytes, path='0.0', kind='SteppingThreadGroup',
                                  params={
                                      'initial_threads': 0, 'step_users': 10,
                                      'step_delay': 30, 'step_count': 10,
                                      'hold': 60, 'shutdown': 5,
                                  })
# kind 取值（5 种）：
#   'ThreadGroup'            → 参数 {users, ramp_up, duration}
#   'SteppingThreadGroup'    → {initial_threads, step_users, step_delay, step_count, hold, shutdown}
#   'ConcurrencyThreadGroup' → {target_concurrency, ramp_up, steps, hold, unit:S|M}
#   'UltimateThreadGroup'    → {users, initial_delay, ramp_up, hold, shutdown}  (单行 schedule)
#   'ArrivalsThreadGroup'    → {target_rps, ramp_up, steps, hold, unit:S|M}
# 边界：用户数 ≤ MAX_USERS=5000；各时间字段 ≤ MAX_DURATION_SECONDS=43200；target_rps ≤ 1_000_000
```

```python
# 9) 跑压测前内存生成可执行 XML（取代 _run.jmx 物理派生，2026-04-28）
from performance.services.jmx import build_run_xml
xml = build_run_xml(task)                              # validate / 默认场景
xml = build_run_xml(task, inject_environment_dns=True) # v1.1 跑 JMeter 时
# 内部步骤（4 步）：
#   1) 链式 replace_thread_group（按 thread_groups_config）
#   2) patch CSVDataSet filename 为绝对路径（按 csv_bindings）
#   3) 可选注入 DNSCacheManager（inject_environment_dns=True + environment.host_entries）
#   4) 可选注入 BackendListener（BackendListenerConfig.enabled=True + influxdb_url 非空）
```

**关键细节**：
- XPath 用 `stringProp` / `intProp` 双兜底（见 `_find_prop`），JMeter 模板有两种写法
- 改 `duration_seconds` 时**自动**把 `ThreadGroup.scheduler` 置 true（否则 JMeter 忽略 duration）
- 多个 ThreadGroup 的情况，**`patch_jmx` 只处理第一个；`list_components` 则全部列出**
- **宽容解析**（2026-04-22 调整）：`parse_jmx` 会搜索多种 ThreadGroup 标签（`ThreadGroup` / `SetupThreadGroup` / `PostThreadGroup` / `kg.apc.jmeter.threads.UltimateThreadGroup` 等），找不到任何 TG 时不抛错，用默认值 `10/0/0` 兜底
- `patch_jmx` 仍然严格：没有标准 `ThreadGroup` 的 `num_threads` / `ramp_time` 属性会抛 `JmxParseError` → view 返回 400
- `list_components` 宽容：缺 `<hashTree>` 返空列表；元素没 `testname` 属性返空串；`enabled` 缺省按 `"true"`
- `toggle_component` 的 `path` 非法/越界抛 `JmxParseError` → view 层 catch 后返 400
- **索引路径语义**：`"0.2.1"` = top-level hashTree 第 0 个组件（TestPlan）→ 它的子 hashTree 第 2 个组件（比如 ThreadGroup）→ 该 ThreadGroup 的子 hashTree 第 1 个组件。代码里 `_hashtree_pairs` 负责把 "元素 + 紧跟的 hashTree" 配对起来
- **`replace_thread_group` 语义**：定位到 path 位置的 ThreadGroup 元素，用 lxml `parent.replace()` 整体替换成新 kind 的元素。**紧跟的 hashTree（装 Samplers/HeaderManager 的那个）保持不动**——这是 Step 2 不破坏原有 Sampler 配置的关键。禁用的 ThreadGroup 前端不展示、PATCH body 也不会包含它们，所以在 JMX 里原样保留（含 enabled=false）。
- **`build_run_xml`**：纯内存操作，无副作用。默认 `inject_environment_dns=False`（validate 用）；v1.1 跑 JMeter 时传 `True` 让 hosts 通过 JMX 内的 `DNSCacheManager` 生效。BackendListener 注入由 `BackendListenerConfig.get_config()` 决定，全局生效，**不需要传参**。
- **`_compute_kind(tag, guiclass)`**：把 XML tag+guiclass 映射成前端规范化 kind。`ConfigTestElement+HttpDefaultsGui` → `'HttpDefaults'`，其余 kind==tag。
- **`_set_any_prop(parent, name, value)`**：更新已有 stringProp/intProp（任一）或新建 stringProp，解决 connect_timeout 等以 intProp 存储的字段的写回问题。
- **`_inject_backend_listener(xml_bytes, cfg)`**：在 TestPlan hashTree 末尾追加完整 BackendListener 元素（含 influxdbMetricsSender / influxdbUrl / application / measurement 等参数 + cfg.extra_args 扩展）。

## 16. Step 2 校验服务（JMeter CLI 版）

**架构**：
```
build_validate_xml(task)            ← jmx.py：原件 → 全部 TG 降级 1×1 → CSV 绑定 → DNS 注入
        ↓
run_jmeter(xml, work_dir)           ← jmeter_runner.py：写 run.jmx → subprocess jmeter -n → 解析 JTL
        ↓
validate_task(task)                 ← validator.py：上面两步合体 + sampler 路径回填
        ↓
list[ValidateResult]                ← 前端表格直接吃
```

```python
# Step 2 校验入口
from performance.services.validator import validate_task, ValidateResult

results: list[ValidateResult] = validate_task(
    task,                                      # ⚠ Task 对象，不是 xml_bytes
    host_entries=[{'hostname': 'a.com', 'ip': '1.2.3.4'}, ...],   # 可选；None 则用 task.environment
)
# 每条 Result：path/testname/url/status/elapsed_ms/ok + 失败时 error
# 前端 ValidateResultTable 直接吃 to_dict()
```

```python
# 内部底层：JMeter 子进程
from performance.services.jmeter_runner import run_jmeter, JtlSample, JMeterRunError
samples: list[JtlSample] = run_jmeter(xml_bytes, work_dir, timeout=120)

# 内部底层：构建校验用 XML（不写盘）
from performance.services.jmx import build_validate_xml, replace_tgs_for_validate
xml = build_validate_xml(task)              # 完整组装（推荐）
xml = replace_tgs_for_validate(orig_xml)    # 仅 TG 降级（不带 CSV / DNS）
```

**关键约定**：
- **TG 降级规则**：所有**启用**的 TG-like 元素（5 种 kind 都算）→ 替换为标准 ThreadGroup(num_threads=1, ramp_time=0, loops=1, scheduler=false)。**禁用的 TG 原样保留**（JMeter 自然不执行）。紧跟的子 hashTree（装 Samplers/HeaderManager 等）保持不动。
- **work_dir**：`<jmeter_home>/runs/_validate_<task_id>/`，每次运行清空重建；存 `run.jmx` + `result.jtl` + `jmeter.log` 供调试
- **JTL 解析**：`csv.DictReader`，强开 `-Jjmeter.save.saveservice.url=true` 让 URL 列写进去；其他列走 JMeter 默认（label/responseCode/success/elapsed/failureMessage 等）
- **路径回填**：JMeter 按 document order 跑 → JTL 顺序通常匹配；用 **testname (label) FIFO 匹配**（同名按出现顺序），多 TG 并行时也能对得上
- **没匹配上的 sampler**（被前面失败 / 控制器跳过）→ 单独一行 `error='未被 JMeter 执行...'`
- **JMeter 退出码非 0**：抛 `JMeterRunError`，message 含 `stderr` 末尾 + `jmeter.log` 末尾 30 行；views 转 500
- **Java 兜底**：mac 上 `/opt/homebrew/opt/openjdk@17` 自动塞 PATH + JAVA_HOME（避免被系统 `/usr/bin/java` stub 劫持）；Docker / Linux 期望 `java` 已经在 PATH
- **chmod +x 兜底**：zipfile 解压不保留 unix 可执行位，`ensure_jmeter_installed` 解压后给 `bin/jmeter` 等加上 0o111

**保真度对比（为什么砍了原来 600 行 Python `requests` 实现）**：

| 能力 | Python requests 实现 | 真 JMeter |
|---|---|---|
| HTTP 请求 | ✅ | ✅ |
| HeaderManager 作用域 | ✅ | ✅ |
| CSV 变量 | ✅ | ✅ |
| **CookieManager** | ❌ | ✅ |
| **AuthManager** | ❌ | ✅ |
| **PreProcessor** | ❌ | ✅ |
| **JSONPostProcessor / RegexExtractor 链式提取** | 90%（自写 mini） | ✅ |
| **`__time` / `__Random` / `__P` 等函数** | ❌ | ✅ |
| **BeanShell / JSR223 脚本** | ❌ | ✅ |
| **断言** | ❌ | ✅ |
| **Synchronizing Timer** | ❌ | ✅ |
| 冷启时间 | < 100ms | **3-5s** |

3-5s 冷启换 100% 保真度 + Step 3 共用同一执行管线 = 划算。

fixture `performance/tests/fixtures/sample.jmx` 是最简实验模板，有 HTTP Sampler + CSVDataSet，parse/patch/components/thread-groups 测试都拿它。

## 17. v1.1 规划（Step 3 执行模块，下一阶段）

### 17.1 数据流
```
PATCH thread-groups (Step 2 入库)
        ↓
POST tasks/:id/run
        ↓
build_run_xml(task, inject_environment_dns=True)   ← 内存生成
        ↓
write to <jmeter_home>/runs/<run_id>/run.jmx       ← 唯一一次落盘（归档）
        ↓
subprocess.Popen('jmeter', '-n', '-t run.jmx',
                 '-l results.jtl', '-e', '-o report/')
        ↓
TaskRun(status=running) + 后台线程/Celery worker tail .jtl
        ↓
每秒聚合 → MetricSample(run, ts, rps, p99_ms, error_rate, active_users)
        ↓
进程退出 → 解析全量 .jtl → 填 TaskRun 汇总指标 → status=success/fail
```

### 17.2 关键模块
1. **`performance/services/executor.py`**：基于 `jmeter_runner.py`（已有，Step 2 校验在用）扩展异步版 —— 当前 `run_jmeter()` 是 `subprocess.run`（同步阻塞），Step 3 真压测需要换成 `subprocess.Popen` + 后台线程 / Celery worker，加 `-e -o <report_dir>` 输出 HTML 报告；维护 `Popen` handle 给 cancel 用
2. **`@action` on TaskViewSet**：
   - `POST /api/performance/tasks/:id/run` → 创建 `TaskRun(status=running)` → 异步起 JMeter → 返回 `{run_id}`
   - `POST /api/performance/runs/:run_id/cancel` → `Popen.terminate()` → status=cancelled
   - `GET /api/performance/runs/:run_id/` → run 详情（含汇总指标）
   - `GET /api/performance/runs/:run_id/metrics?since=<ts>` → 增量时序点
   - `GET /api/performance/tasks/:id/runs/` → 历史 run 列表
3. **JTL 结果解析**：`.jtl` 是 CSV 格式（`timeStamp,elapsed,label,responseCode,responseMessage,...`），读完算 `avg_rps` / `p99_ms` / `error_rate` / `total_requests` 填回 `TaskRun`
4. **时序采样**：执行期间每秒 tail `.jtl` 新增行，聚合成一个 `MetricSample` 写 DB
5. **执行器选型**：v1 dev 阶段用 Python `threading.Thread` 跑通；上量必须 **Celery + Redis**（subprocess 直接跑会卡住 gunicorn worker）
6. **压力机管理**（v1.2+）：当前 master = web 进程同主机；以后加 `LoadGenerator` 模型 + 远程 JMeter slave（`-R <host:port>`）
7. **磁盘空间**：每次 run 落盘 `runs/<run_id>/{run.jmx, results.jtl, report/}`，长跑 .jtl 可能上 GB；v1.1 加"自动清理超过 N 天 / 仅保留最新 M 个 run"策略

### 17.3 Step 2 还要补的（执行前必须）
- **Environment DNS 注入实测**：`build_run_xml(inject_environment_dns=True)` 已实现 `DNSCacheManager` 注入逻辑，但还没真跑过 JMeter 验证 hosts 生效
- **TG 参数与 JMeter 字段对齐**：ArrivalsThreadGroup 的 `ConcurrencyLimit / LogFilename / Iterations`、Stepping 的"每步内部 ramp"等当前写死兜底值，需暴露给前端调
- **"压测的服务"字段**：Task 加 `service` FK → Service 模型（含 grafana_url / pinpoint_app / arthus_endpoint）；Step 2 选择 service 后 → Step 3 跑完拉对应监控数据 → AI 对比报告。服务未接入监控时退化为"仅 JTL 总结 + 接入指引"

## 18. JMeter 工具与脚本存储（v1 已落地）

### 18.1 本地开发
- JMeter 工具路径（固定）：`backend/jmeter/apache-jmeter-<VERSION>/`
- JMX 物理文件存放路径：`backend/jmeter/apache-jmeter-<VERSION>/scripts/<title>.jmx`
- `Task.jmx_filename` CharField 只存文件名（不含路径），`Task.jmx_path()` 返回绝对路径
- **默认 `JMETER_VERSION=5.4.1`**（代码层兜底），但**当前推荐 `5.6.3`**（最新稳定）—— 在 `.env` 写 `JMETER_VERSION=5.6.3` 切换；切换后要重跑 `setup_jmeter` 才会下载新版。Mac 首装就直接走 5.6.3。
- `performance/services/jmeter.py` 负责：工具下载、脚本目录管理、文件名清洗
- **设计约定**：工具路径永远是项目内 `backend/jmeter/...`，**不读 `JMETER_HOME` 环境变量**（避免被系统全局 JMeter 装载 hijack 路径）
- **JMeter 启动需要 Java 17+**（5.6.3 要求）。Mac：`brew install openjdk@17` + `start.sh` 把 `/opt/homebrew/opt/openjdk@17/bin` 加进 PATH；Windows：装 JDK 17 让 `java` 进 PATH 即可。`setup_jmeter` 本身不依赖 Java（只下载解压）。

- **首次创建任务会阻塞 1-2 分钟下载 JMeter (~100MB)**，或提前跑一次：
  ```bash
  # Mac/Linux
  ./venv/bin/python manage.py setup_jmeter
  # Windows
  ./venv/Scripts/python.exe manage.py setup_jmeter
  ```

### 18.2 文件名规则
- 任务 title 直接用用户输入（**2026-04-28 取消日期前缀**）
- 文件名 = `sanitize_script_name(title) + '.jmx'`；非法字符 (`< > : " / \\ | ? *` 及控制符) 剔除，中文保留
- 冲突时追加 `_2`、`_3`
- Windows 保留名 (CON/PRN/...) 加下划线前缀防爆
- CSV 命名：`<jmx_stem>__<safe_path>.csv`（按 `TaskCsvBinding.component_path` 决定，path 的 `.` 换 `_`，例 `0.0.3` → `0_0_3`）

### 18.3 写盘安全保护（2026-04-28）
- `write_script` / `write_csv` 写盘前 `shutil.disk_usage()` 检查 < 100 MB → 抛 `DiskFullError`，views 转 503 + 明确文案
- 实际写盘走 `_atomic_write_bytes(path, data)`：open + write + flush + `os.fsync(f.fileno())`，确保 bytes 落盘后才返回，避免半写文件被 JMeter 读到
- 新增 `get_runs_dir() → <jmeter_home>/runs/`，给 v1.1 执行模块的 `runs/<run_id>/run.jmx` + `results.jtl` 准备

### 18.3 Docker 部署（v1.2+）
**不要**让容器首次请求时下载 JMeter——慢、可能无外网、每次重启重下。由于代码固定用 `backend/jmeter/apache-jmeter-<VERSION>/` 这个路径，Dockerfile 在构建期就把 JMeter 解压到这里，**代码零改动**。

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ARG JMETER_VERSION=5.6.3

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless wget unzip \
    && mkdir -p /app/backend/jmeter \
    && wget -q https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.zip -O /tmp/jmeter.zip \
    && unzip -q /tmp/jmeter.zip -d /app/backend/jmeter \
    && rm /tmp/jmeter.zip \
    && apt-get purge -y wget unzip && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ /app/backend/
# openjdk-17-jre-headless 提供 JMeter CLI 所需的 Java runtime
```

docker-compose 挂 volume 让脚本跨容器重启保留：
```yaml
services:
  backend:
    build: .
    volumes:
      - jmeter_scripts:/app/backend/jmeter/apache-jmeter-5.6.3/scripts
volumes:
  jmeter_scripts:
```

关键是：**镜像里 JMeter 要解压到 `/app/backend/jmeter/apache-jmeter-<VERSION>/`，路径跟 Django `BASE_DIR` 下的 `jmeter/` 对齐**，运行时 `ensure_jmeter_installed()` 检测到已有 `bin/jmeter` 就直接返回，不触发下载。

### 18.4 软删除
- `Task.delete()` = 设 `is_deleted=True` + 物理删除 .jmx + 全部 csv_bindings（含物理 CSV）；DB 行保留
- 默认 `Task.objects.all()` 过滤掉软删除
- Admin 用 `Task.all_objects` 看全量（包括已删）；管理界面 Task 详情内嵌 `TaskCsvBinding` inline
- 真要删行用 `instance.hard_delete()`（API 没暴露）
