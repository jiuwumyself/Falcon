"""
Django settings for config project.

Database configuration:
- Defaults to SQLite at backend/db.sqlite3 (no external service required).
- To use PostgreSQL, set these in backend/.env:
    DB_ENGINE=postgres
    DB_NAME=falcon
    DB_USER=postgres
    DB_PASSWORD=your_password
    DB_HOST=localhost
    DB_PORT=5432
  (psycopg is already installed — just uncomment/set the env vars.)
"""

from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env (optional) from backend/.env
load_dotenv(BASE_DIR / '.env')


SECRET_KEY = os.getenv(
    'DJANGO_SECRET_KEY',
    'django-insecure-rf&v*8u=os4_o1=yo=6&z$=p+b!xlu-u&im78u^0%bg5r(1$c9',
)

DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'

# 内部固定允许的 Host（恒定，不随 DJANGO_ALLOWED_HOSTS env 覆盖而丢失）：
# - localhost/127.0.0.1：本机
# - host.docker.internal：docker-compose 下 falcon-agent 回调主控的 Host header
# - falcon-backend：K8s 集群内 agent 用后端 Service 名回调主控的 Host header
#   （少了它 agent 注册会被 DisallowedHost 拒掉；放这里保证重启/重新部署都不丢）
# 公网域名等其它 Host 仍通过 DJANGO_ALLOWED_HOSTS env 追加（逗号分隔）。
_ALWAYS_ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'host.docker.internal', 'falcon-backend']
ALLOWED_HOSTS = _ALWAYS_ALLOWED_HOSTS + [
    h.strip() for h in os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()
]


INSTALLED_APPS = [
    'jazzmin',  # 现代化 admin 主题（必须排在 django.contrib.admin 之前）
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'performance',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise 托管 admin/DRF/jazzmin 静态（生产 waitress 单进程下无需 nginx 转 static）。
    # 必须紧跟 SecurityMiddleware。
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
#
# 在 K8s 集群里（KUBERNETES_SERVICE_HOST 由 K8s 自动注入）默认连阿里云 RDS PostgreSQL，
# 配置写死在代码里——这样后端 pod 重启/重新部署都不依赖 env、不丢配置（SQLite 在 K8s 里
# 是每个 pod 一份临时空库，根本不能用）。本地开发（无该 env）仍走 SQLite，不会误连生产库。
# 各项仍可被同名环境变量覆盖（DB_HOST/DB_NAME/...）。
# ⚠️ 注意：DB_PASSWORD 默认值是生产库明文密码，已随代码进 git（用户知情接受）；
#    换密码时记得同步改这里。
_IN_K8S = bool(os.getenv('KUBERNETES_SERVICE_HOST'))
_USE_POSTGRES = os.getenv('DB_ENGINE', 'postgres' if _IN_K8S else 'sqlite') == 'postgres'

if _USE_POSTGRES:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'Falcon'),
            'USER': os.getenv('DB_USER', 'Falcon'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'V1TD#(*&fiV6'),
            'HOST': os.getenv('DB_HOST', 'pgm-bp1nm1m734hzvi23.pg.rds.aliyuncs.com'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
# 生产 collectstatic 目标；WhiteNoise 从这里托管。dev 也无害（runserver 仍走 app static）。
STATIC_ROOT = BASE_DIR / 'staticfiles'
# 自带静态（后台品牌 logo + 自定义主题 CSS，对齐前端设计语言）
STATICFILES_DIRS = [BASE_DIR / 'static']
# WhiteNoise 压缩 + 带 hash 的静态文件存储（长缓存）
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

# CSRF 信任来源（admin 在 https ingress 后面 POST 需要；逗号分隔，如
# https://falcon.zhihuishu.com）。空 = 不额外信任（dev 同源无需）。
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()
]

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Upload caps — align with the 10 MB .jmx limit enforced in views.
# Without these, Django would fall back to its defaults (2.5 MB → spill to disk,
# 2.5 MB request body cap) which don't match our 10 MB product rule.
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# DRF
REST_FRAMEWORK = {
    # 平台暂不做认证（CLAUDE.md §7）。显式清空，避免 DRF 默认的
    # SessionAuthentication 在浏览器有 admin session cookie 时触发 CSRF 校验。
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}


# CORS: let the Vite dev server (localhost:5173) talk to Django.
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://127.0.0.1:5173',
).split(',')


# InfluxDB v1.x — Step 3 实时指标管道。
# JMeter Backend Listener 直接 POST /write?db=<INFLUXDB_DB>，写入由它做；
# performance/services/influxdb.py 只读取查询结果给前端展示。
INFLUXDB_URL = os.getenv('INFLUXDB_URL', 'http://localhost:8086')
INFLUXDB_DB = os.getenv('INFLUXDB_DB', 'jmeter')
INFLUXDB_USER = os.getenv('INFLUXDB_USER', '')
INFLUXDB_PASSWORD = os.getenv('INFLUXDB_PASSWORD', '')
INFLUXDB_RETENTION = os.getenv('INFLUXDB_RETENTION', '30d')

# 磁盘治理：run 目录(results.jtl/report 等重文件)按天数 TTL 淘汰 —— 勾选「保留」
# (TaskRun.keep=True)的永不删,未勾选的 mtime 超 RUN_RETENTION_DAYS 天才整删 + 同步清
# InfluxDB(分析数据已入 DB,查历史走库不依赖文件)。详见 cleanup_old_runs。
# RUN_KEEP_COUNT 旧的"最近 N 个"计数淘汰已弃用(保留变量兼容),改走 RUN_RETENTION_DAYS。
RUN_KEEP_COUNT = int(os.getenv('RUN_KEEP_COUNT', '5'))
RUN_RETENTION_DAYS = int(os.getenv('RUN_RETENTION_DAYS', '30'))

# v1.2 多机调度：JMX 烤进 BackendListener 的 InfluxDB URL 是 agent 容器从内访问宿主
# InfluxDB 用的，跟主控读 InfluxDB 用的 INFLUXDB_URL 不同。Mac/Win Docker Desktop 自带
# host.docker.internal；Linux 靠 docker-compose 的 extra_hosts: host-gateway 兜底。
AGENT_INFLUXDB_URL = os.getenv(
    'AGENT_INFLUXDB_URL',
    'http://host.docker.internal:8086',
)

# v1.2 容器化压力源（OrchestratorAdapter）
ORCHESTRATOR_TYPE = os.getenv('ORCHESTRATOR_TYPE', 'docker')   # docker / k8s
AGENT_COMPOSE_FILE = os.getenv('AGENT_COMPOSE_FILE', '')        # 默认 BASE_DIR/docker-compose.dev.yml
AGENT_COMPOSE_SERVICE = os.getenv('AGENT_COMPOSE_SERVICE', 'agent')
AGENT_COMPOSE_PROJECT = os.getenv('AGENT_COMPOSE_PROJECT', None)
AGENT_K8S_NAMESPACE = os.getenv('AGENT_K8S_NAMESPACE', 'falcon')
AGENT_K8S_DEPLOYMENT = os.getenv('AGENT_K8S_DEPLOYMENT', 'falcon-agent')

MAX_VUSERS_PER_AGENT = int(os.getenv('MAX_VUSERS_PER_AGENT', '100'))
IDLE_RELEASE_MINUTES = int(os.getenv('IDLE_RELEASE_MINUTES', '30'))
FALCON_AGENT_TOKEN = os.getenv('FALCON_AGENT_TOKEN', '')        # 空 = 不强校验（开发态）

# 选了 0 台 agent + LOCAL_FALLBACK=True → executor 走单机本地 jmeter（开发态友好）
# 生产环境建议 LOCAL_FALLBACK=0 强制走分布式
LOCAL_FALLBACK = os.getenv('LOCAL_FALLBACK', '1') == '1'

# SSH 型压力机（LoadGenerator.transport='ssh'）：主控 SSH 进机器直接跑 jmeter。
# 密码走本机凭据文件（一行密码，chmod 600），不在 DB 存明文。同密码的多台机器
# 共用此文件。executor 用 `sshpass -f <此文件>` 连。
SSH_PASSWORD_FILE = os.getenv('SSH_PASSWORD_FILE', '~/.ssh/.lgpw')

# 定时任务（run_due_schedules 命令）触发自身 run 接口的地址。RunExecutor 线程必须在
# 长驻 web 进程里，故定时命令走 HTTP POST 触发，不在命令进程直接起 executor。
# 本地 = http://localhost:8000；K8s = http://falcon-backend:8000。
FALCON_SELF_URL = os.getenv('FALCON_SELF_URL', 'http://localhost:8000')

# CSV 切片策略（v1.2 多机）：默认 False → 各 agent 拿同一份完整 CSV（字典表 / 共享
# 参数场景）；True → executor 调 scheduler.slice_csv_by_offset 按行模分片上传，
# 各 agent 只拿自己那部分（账号池等"每条数据只能用一次"场景）。
# 开发态 .env 设 CSV_SLICE_ENABLED=true 开启。粒度暂时全 task 全 binding；
# per-binding 控制留到将来给 TaskCsvBinding 加字段。
# ── Prometheus 监控缓存配置 ─────────────────────────────
# 缓存 Prometheus 查询结果，避免重复查询（15-30 秒 TTL）
# 使用 Django 内存缓存（无需 Redis），适合单机部署
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'prometheus-cache',
        'OPTIONS': {
            'MAX_ENTRIES': 1000,
            'CULL_FREQUENCY': 3,
        }
    },
    # 标签探测缓存：5 分钟（数据源配置极少变动）
    'prometheus_labels': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'prometheus-labels-cache',
        'TIMEOUT': 300,  # 5 分钟
    },
}

# 指标查询结果缓存时间（秒）
PROMETHEUS_QUERY_CACHE_TTL = int(os.getenv('PROMETHEUS_QUERY_CACHE_TTL', '15'))

CSV_SLICE_ENABLED = os.getenv('CSV_SLICE_ENABLED', '').lower() == 'true'


# ── Jazzmin（现代化 admin 主题）────────────────────────────────────────────
# Falcon 暗色玻璃质感的延伸：左侧导航 + 暗色主题 + 图标 + 顶部搜索
JAZZMIN_SETTINGS = {
    'site_title': 'Falcon 猎鹰 · 后台',
    'site_header': 'Falcon 猎鹰',
    'site_brand': 'Falcon 猎鹰',
    'welcome_sign': 'Falcon 猎鹰 · 性能压测调度平台',
    'copyright': 'Falcon 猎鹰',
    # 前端品牌图标（FalconLogo 转静态 SVG）+ 自定义主题（对齐前端暗色设计语言）
    'site_logo': 'admin_brand/falcon-logo.svg',
    'login_logo': 'admin_brand/falcon-logo.svg',
    'site_logo_classes': 'img-fluid',  # 不裁成圆形（logo 是箭羽形）
    'custom_css': 'admin_brand/falcon-admin.css',
    # 顶部搜索框搜这些模型
    'search_model': ['performance.Task', 'performance.Service'],
    # 顶栏链接（全中文）
    'topmenu_links': [
        {'name': '回前端', 'url': 'http://localhost:5173', 'new_window': True},
        {'name': '压测任务', 'model': 'performance.task'},
        {'name': '定时任务', 'model': 'performance.taskschedule'},
        {'model': 'auth.user'},
    ],
    'show_sidebar': True,
    'navigation_expanded': True,
    'hide_apps': [],
    'hide_models': [],
    # app / model 排序：性能压测 在前
    'order_with_respect_to': ['performance', 'auth'],
    # FontAwesome 图标
    'icons': {
        'auth': 'fas fa-users-cog',
        'auth.user': 'fas fa-user',
        'auth.Group': 'fas fa-users',
        'performance.Task': 'fas fa-bolt',
        'performance.TaskRun': 'fas fa-play-circle',
        'performance.TaskSchedule': 'fas fa-clock',
        'performance.Environment': 'fas fa-server',
        'performance.Service': 'fas fa-cubes',
        'performance.PrometheusDataSource': 'fas fa-chart-line',
        'performance.PinpointConfig': 'fas fa-project-diagram',
        'performance.BackendListenerConfig': 'fas fa-broadcast-tower',
        'performance.LoadGenerator': 'fas fa-microchip',
        'performance.MetricSample': 'fas fa-wave-square',
        'performance.RunEventAnchor': 'fas fa-map-pin',
        'performance.RunPinpointTrace': 'fas fa-route',
    },
    'default_icon_parents': 'fas fa-chevron-circle-right',
    'default_icon_children': 'fas fa-circle',
    'related_modal_active': True,
    'changeform_format': 'horizontal_tabs',
    'show_ui_builder': False,
}

JAZZMIN_UI_TWEAKS = {
    'theme': 'darkly',           # Bootswatch 暗色底，custom_css 再覆成前端配色
    'default_theme_mode': 'dark',  # 强制暗色（jazzmin 3.0 起 dark_mode_theme 废弃）
    'navbar': 'navbar-dark',
    'navbar_fixed': True,
    'sidebar_fixed': True,
    'sidebar': 'sidebar-dark-primary',
    'sidebar_nav_compact_style': True,
    'accent': 'accent-primary',  # 蓝色主色（对齐前端 #3b82f6）
    'brand_colour': 'navbar-dark',
    'body_small_text': False,
    'sidebar_nav_flat_style': False,
    'actions_sticky_top': True,
    'button_classes': {
        'primary': 'btn-primary',
        'secondary': 'btn-secondary',
        'info': 'btn-info',
        'warning': 'btn-warning',
        'danger': 'btn-danger',
        'success': 'btn-success',
    },
}


# ── AI 压测分析（OpenAI 兼容端点；qoder-proxy 或任意兼容网关）──
# qoder 无官方 HTTP API，需一个 OpenAI 兼容 /chat/completions 端点。base_url 留空 =
# AI 分析按钮提示「未配置」，不影响算法结论。密钥只在后端，前端永远拿不到。
AI_BASE_URL = os.getenv('AI_BASE_URL', '')      # 如 http://localhost:3000/v1
AI_API_KEY = os.getenv('AI_API_KEY', '')        # qoder PAT(pt-...) 或网关 key
AI_MODEL = os.getenv('AI_MODEL', 'auto')        # qoder-proxy: auto/ultimate/lite/qwen/deepseek...
AI_TIMEOUT = int(os.getenv('AI_TIMEOUT', '90'))
