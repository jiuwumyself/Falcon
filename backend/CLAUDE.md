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
│   ├── models.py           Task / TaskRun / MetricSample / Environment 四张表
│   ├── serializers.py      Task / TaskRun / MetricSample / Environment Serializer
│   ├── views.py            TaskViewSet + EnvironmentViewSet
│   ├── urls.py             DefaultRouter 注册两个 ViewSet（URL 前缀 `/api/performance/`）
│   ├── admin.py            四张表都用 @admin.register 装饰器注册
│   ├── services/
│   │   ├── __init__.py
│   │   ├── jmeter.py       ★ JMeter 工具 + 插件下载 + 脚本文件存储
│   │   ├── jmx.py          ★ parse_jmx / patch_jmx / list_components / toggle_component /
│   │   │                   ★ list_thread_groups / replace_thread_group（lxml 实现）
│   │   └── validator.py    ★ Step 2 "1 并发校验"：collect_effective_headers + validate_task
│   ├── management/commands/setup_jmeter.py   JMeter + 插件一键安装
│   ├── tests/
│   │   ├── __init__.py
│   │   └── fixtures/sample.jmx    有 ThreadGroup + CSVDataSet + HTTPSampler 的最小 JMX
│   └── migrations/         0001_initial / 0002_csv_to_scripts / 0003_environment_and_run_jmx
├── media/                  上传文件：jmx/<task_id>/*.jmx、csv/<task_id>/*.csv（gitignored）
├── manage.py
├── db.sqlite3              默认数据库（gitignored）
├── .env                    本地环境变量（gitignored，不要提交）
├── .env.example            模板（已提交）
├── requirements.txt
└── venv/                   Python 虚拟环境（gitignored）
```

**约定**：`config/` **只放项目级配置**（settings、urls、wsgi），**不要往里塞 models / views**。所有业务代码一定要在 app 里（比如 `tasks/`）。

## 3. 运行命令（Windows 注意事项）

venv 在 Windows 下是 `Scripts/`（不是 Linux 的 `bin/`），直接用绝对路径更不容易出错：

```bash
# 在 backend/ 目录下执行
./venv/Scripts/python.exe manage.py runserver           # 默认 http://localhost:8000
./venv/Scripts/python.exe manage.py migrate
./venv/Scripts/python.exe manage.py makemigrations
./venv/Scripts/python.exe manage.py makemigrations <app_name>
./venv/Scripts/python.exe manage.py shell
./venv/Scripts/python.exe manage.py createsuperuser
./venv/Scripts/python.exe manage.py check
./venv/Scripts/python.exe manage.py startapp <app_name>
./venv/Scripts/python.exe manage.py test

# pip
./venv/Scripts/pip.exe install -r requirements.txt
./venv/Scripts/pip.exe install <pkg>
./venv/Scripts/pip.exe freeze > requirements.txt
```

**不要用** `python manage.py ...`（系统 Python 可能不是 3.12，也没装依赖）。**也不要** `source venv/bin/activate`（Windows 风格 venv 没这路径）。

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
| **CSV 作用域变量替换**（`validator.py::collect_effective_csv_vars` + `substitute_vars`）| ✅ |
| **Environment 模型**（name / is_default / host_entries JSONField）+ admin 编辑 | ✅ |
| **派生可执行脚本 `.run.jmx`**（Task.run_jmx_filename + thread_groups_config）| ✅ |
| **插件自动安装**（ensure_plugins_installed：jmeter-plugins-casutg + cmn-jmeter）| ✅ |
| **1 并发校验**（`performance/services/validator.py`：HeaderManager 作用域合并 + Python requests）| ✅ |
| 压测执行引擎（调 JMeter CLI） | ❌ v1.1 |
| MetricSample 时序写入 | ❌ v1.1（表建了，暂无写入） |
| 异步调度（Celery + Redis） | ❌ v1.1 |
| 认证（JWT） | ❌ 故意不做 |
| Ultimate ThreadGroup 参数编辑 | ❌ Step 2 不做；建议用户改用 Stepping |
| 集合点测试（Synchronizing Timer）模式预设 | ❌ v1.1 |

## 8. 已落地的业务模型（见 `performance/models.py`）

```
Environment (压测环境，hosts 映射等，Step 2 用)
Task (压测任务定义 + JMX 文件 + Step 2 派生 .run.jmx)
 └─── TaskRun (一次执行记录，v1.1 才会有数据)
       └─── MetricSample (时序采样点，v1.1 才会有数据)
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
- `csv_filename`（CharField，bare 文件名，空串表示未传）—— 物理文件和 .jmx 同放 `<JMETER_HOME>/scripts/`，命名 `<jmx_stem>.csv`
- **JMX 解析字段**：`virtual_users`、`ramp_up_seconds`、`duration_seconds` — 这三个字段与 JMX 文件里的 `ThreadGroup` 内容**保持同步**；Step 2 保存时也会同步（用第一个启用的标准 TG 的参数）
- **Step 2 字段**（新增）：
  - `run_jmx_filename`（CharField，空串 = 还没做过 Step 2 配置）—— 派生可执行脚本，命名 `<jmx_stem>_run.jmx`，物理文件同在 scripts/ 下
  - `thread_groups_config`（JSONField，默认 `[]`）—— `[{"path":"0.0","kind":"ThreadGroup","params":{...}}, ...]`
  - `environment`（FK → Environment, nullable）
- `owner`（FK User，nullable）
- `is_deleted` / `deleted_at`（软删除标记）
- `created_at` / `updated_at`
- **Manager**：`Task.objects`（默认，过滤掉软删）/ `Task.all_objects`（全量，admin 用）
- **方法**：`delete()` 软删 + 物理删文件（jmx/run_jmx/csv 都清）；`hard_delete()` 真·删行；`jmx_path()`/`run_jmx_path()`/`csv_path()` + `read_*_bytes()`/`write_*_bytes()` 三套平行读写 API

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

新建 app 的完整流程：
1. `./venv/Scripts/python.exe manage.py startapp <name>`
2. 在 `config/settings.py` 的 `INSTALLED_APPS` 追加 `'<name>'`
3. 写 `models.py`
4. `./venv/Scripts/python.exe manage.py makemigrations <name>`
5. `./venv/Scripts/python.exe manage.py migrate`
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
| `POST` | `/api/performance/tasks/:id/upload-csv/` | 单独上传 CSV（字段名 `csv_file`）；校验 10MB 上限；落盘到 `scripts/<jmx_stem>.csv`；覆盖旧 CSV（如有） |
| `POST` | `/api/performance/tasks/:id/replace-jmx/` | 覆盖同一任务的 JMX（multipart，字段名 `jmx_file`）；保留 title/biz/description/csv_file/created_at，仅换 jmx 内容 + 重 parse vuser/ramp/duration + 更 `jmx_hash`；磁盘文件名不变 |
| `GET` | `/api/performance/tasks/:id/raw-xml/` | 返回 `{ xml: "..." }` |
| `GET` | `/api/performance/tasks/:id/download/` | 二进制 JMX 下载 |
| `GET` | `/api/performance/tasks/:id/components/` | 组件树 `[JmxComponent]`（按 `<hashTree>` 配对结构递归；每项 `path/tag/testname/enabled/children`） |
| `POST` | `/api/performance/tasks/:id/components/toggle/` | body `{path, enabled}` → 定位组件改 `enabled` 属性，写盘，返回新树 |
| `POST` | `/api/performance/tasks/:id/components/rename/` | body `{path, testname}` → 定位组件改 `testname` 属性（允许空串），写盘，返回新树 |
| `GET` | `/api/performance/tasks/:id/components/detail/?path=...` | 返回该组件的编辑字段结构。HTTPSamplerProxy → `{kind, domain, port, protocol, method, path, bodyMode, params:[{name,value}], body, files:[{path,paramname,mimetype}]}`；HeaderManager → `{kind, headers:[{name,value}]}`；其他 tag 返 400 |
| `PATCH` | `/api/performance/tasks/:id/components/detail/` | body `{path, kind, fields}` → 按 kind 写回（HTTPSampler 带 bodyMode 时重建 Arguments collection + 切换 `HTTPSampler.postBodyRaw`；带 files 时重建 Files collection；HeaderManager 整条 collectionProp 重建），写盘，返回新树 |
| `GET` | `/api/performance/tasks/:id/thread-groups/` | 返回 `{thread_groups:[{path,kind,tag,testname,enabled,current_params}], saved_config, environment}`；前端 Step 2 初始化用 |
| `PATCH` | `/api/performance/tasks/:id/thread-groups/` | body `{thread_groups:[{path,kind,params}], environment_id}`；按配置**从原件重新生成** `<jmx_stem>_run.jmx`；Stepping/Concurrency 会按需调 `ensure_plugins_installed()`；保存 `thread_groups_config` + `environment` 到 Task |
| `POST` | `/api/performance/tasks/:id/validate/` | body `{environment_id?}`；遍历启用的 HTTPSampler 各发一次请求（读 .run.jmx 若存在否则原件；按 HeaderManager 作用域合并；Environment.host_entries 映射通过 IP 直连 + Host 头）；返回 `[{path,testname,url,status,elapsed_ms,ok,error?}]` |
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

### 13.1 venv 是 Windows 风格
激活用 `./venv/Scripts/activate`（bat）或 `./venv/Scripts/Activate.ps1`（PowerShell），但**更推荐不激活，直接用 `./venv/Scripts/python.exe` 绝对路径**——省掉忘记激活导致调用错 Python 的坑。

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

```bash
# 进 shell 直接操作 ORM
./venv/Scripts/python.exe manage.py shell
>>> from performance.models import Task
>>> Task.objects.create(title='Test', target_url='https://example.com', ...)

# 看 SQL
./venv/Scripts/python.exe manage.py sqlmigrate tasks 0001

# 看路由
./venv/Scripts/python.exe manage.py show_urls    # 需要装 django-extensions，或者
./venv/Scripts/python.exe -c "from django.urls import get_resolver; [print(p) for p in get_resolver().reverse_dict]"

# 重置数据库（开发期用）
rm db.sqlite3
./venv/Scripts/python.exe manage.py migrate
./venv/Scripts/python.exe manage.py createsuperuser
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
# 每个 JmxComponent 有 path(索引路径如 "0.0.1") / tag / testname / enabled / children

# 4) Step 1 切换某个组件的 enabled 属性
new_bytes: bytes = toggle_component(xml_bytes, path="0.2.1", enabled=False)

# 5) Step 1 重命名组件（改 testname 属性）
new_bytes: bytes = rename_component(xml_bytes, path="0.2.1", testname="Login 接口")

# 6) Step 1 抽屉编辑（仅 HTTPSamplerProxy / HeaderManager）
detail = get_component_detail(xml_bytes, path="0.0.1")
# HTTPSampler 返的字段：
# {'kind', 'domain', 'port', 'protocol', 'method', 'path',
#  'bodyMode': 'params'|'raw', 'params': [...], 'body': str,
#  'files': [{'path','paramname','mimetype'}, ...]}
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

## 16. Step 2 校验服务 `performance/services/validator.py`

```python
from performance.services.validator import (
    collect_effective_headers, collect_effective_csv_vars,
    substitute_vars, validate_task, ValidateResult,
)

# 按 JMeter 作用域规则计算某 Sampler 的有效 headers
headers = collect_effective_headers(xml_bytes, sampler_path='0.0.1')
# 从根到 Sampler 沿路径各层的 HeaderManager 都继承，同名取最近的一个。

# 同一套作用域规则算 CSV 提供的变量字典（读每个 CSVDataSet 的物理文件第一行）
vars = collect_effective_csv_vars(xml_bytes, sampler_path='0.0.1')
# {'username': 'alice', 'password': 's3cret', ...}

# 在任何字符串里替换 ${name}
text, unresolved = substitute_vars('login ${username}', vars)
# 未命中的名字（含 __BASE64 等函数）收集到 unresolved 返回给调用方

# 对所有启用的 HTTPSampler 各发一次请求
results: list[ValidateResult] = validate_task(
    xml_bytes,
    host_entries=[{'hostname': 'api.foo.com', 'ip': '10.0.0.1'}, ...],
)
# 每条 Result 带 unresolved_vars（如果有），前端展示黄色警告。
# 禁用的 Sampler 跳过；失败不中断，结果带 error。
# timeout=10 秒/条；verify=False（IP 直连 + Host 头时 cert 必然不匹配）。
```

**关键细节**：
- 只支持 HTTPSamplerProxy；其他 Sampler 类型忽略
- Environment.host_entries 映射的实现：URL 里用 IP 替换域名 + 设置 `Host` header —— 这样不依赖系统 DNS，不污染远程机 hosts
- Body mode 跟随 JMX 的 `HTTPSampler.postBodyRaw`：true → 整条 Argument.value 作 body；false → params 作 query string / form
- **CSV 作用域**跟 HeaderManager 同规则：TestPlan 级 → 全局；ThreadGroup 级 → 该组 Sampler；Sampler 级 → 仅该 Sampler。近的覆盖远的。物理文件从 `get_scripts_dir()` 下找（只用 basename 防路径穿越）；每个 CSV 读**第一行**模拟 1 并发取值
- **变量替换范围**：URL domain/port/path、params name/value、body、header name/value；`__xxx` 形式的 JMeter 内置函数（`__BASE64`、`__P`、`__Random` 等）不展开、报为未解析
- 不做正则提取 / Pre-Post Processors / 断言——这些是 JMeter 执行引擎的活

fixture `performance/tests/fixtures/sample.jmx` 是最简实验模板，有 HTTP Sampler + CSVDataSet，parse/patch/components/thread-groups 测试都拿它。

## 17. v1.1 规划（下一阶段）

1. **`performance/services/executor.py`**：用 `subprocess` 调 `jmeter -n -t <jmx> -l <jtl> -e -o <report_dir>`
2. **`@action` on TaskViewSet**：`POST /api/performance/tasks/:id/run` → 创建 `TaskRun(status=running)` → 异步起 JMeter → 返回 run id
3. **JTL 结果解析**：`.jtl` 是 CSV 格式，读完算 `avg_rps` / `p99_ms` / `error_rate` / `total_requests` 填回 `TaskRun`
4. **时序采样**：执行期间每秒 tail `.jtl` 新增行，聚合成一个 `MetricSample` 写 DB
5. **Celery + Redis**：subprocess 直接跑会卡住 gunicorn worker，必须 Celery 异步化
6. **前端查询 run**：新端点 `GET /api/performance/tasks/:id/runs/`、`GET /api/runs/:id/metrics?since=<ts>` 供前端轮询画图

## 18. JMeter 工具与脚本存储（v1 已落地）

### 18.1 本地开发
- JMeter 工具路径（固定）：`backend/jmeter/apache-jmeter-<VERSION>/`
- JMX 物理文件存放路径：`backend/jmeter/apache-jmeter-<VERSION>/scripts/<title>.jmx`
- `Task.jmx_filename` CharField 只存文件名（不含路径），`Task.jmx_path()` 返回绝对路径
- **默认 `JMETER_VERSION=5.4.1`**，通过 `.env` 可改（但改了要重新 setup_jmeter）
- `performance/services/jmeter.py` 负责：工具下载、脚本目录管理、文件名清洗
- **设计约定**：工具路径永远是项目内 `backend/jmeter/...`，**不读 `JMETER_HOME` 环境变量**（避免被系统全局 JMeter 装载 hijack 路径）

- **首次创建任务会阻塞 1-2 分钟下载 JMeter (~100MB)**，或提前跑一次：
  ```bash
  ./venv/Scripts/python.exe manage.py setup_jmeter
  ```

### 18.2 文件名规则
- 任务 title 创建时自动加日期前缀：`YYYY-MM-DD_<用户输入>`
- 文件名 = `sanitize_script_name(title) + '.jmx'`；非法字符 (`< > : " / \\ | ? *` 及控制符) 剔除，中文保留
- 冲突时追加 `_2`、`_3`
- Windows 保留名 (CON/PRN/...) 加下划线前缀防爆

### 18.3 Docker 部署（v1.2+）
**不要**让容器首次请求时下载 JMeter——慢、可能无外网、每次重启重下。由于代码固定用 `backend/jmeter/apache-jmeter-<VERSION>/` 这个路径，Dockerfile 在构建期就把 JMeter 解压到这里，**代码零改动**。

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ARG JMETER_VERSION=5.4.1

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
      - jmeter_scripts:/app/backend/jmeter/apache-jmeter-5.4.1/scripts
volumes:
  jmeter_scripts:
```

关键是：**镜像里 JMeter 要解压到 `/app/backend/jmeter/apache-jmeter-<VERSION>/`，路径跟 Django `BASE_DIR` 下的 `jmeter/` 对齐**，运行时 `ensure_jmeter_installed()` 检测到已有 `bin/jmeter` 就直接返回，不触发下载。

### 18.4 软删除
- `Task.delete()` = 设 `is_deleted=True` + 物理删除 scripts/ 下的 .jmx + 删 CSV（DB 行保留）
- 默认 `Task.objects.all()` 过滤掉软删除
- Admin 用 `Task.all_objects` 看全量（包括已删）
- 真要删行用 `instance.hard_delete()`（API 没暴露）
