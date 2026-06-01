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

# host.docker.internal: v1.2 falcon-agent 容器调主控时的 Host header（macOS/Win Docker
# Desktop 内置；Linux 走 compose 的 extra_hosts）。少这条 agent 注册会被 DisallowedHost 拒掉。
ALLOWED_HOSTS = os.getenv(
    'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,host.docker.internal',
).split(',')


INSTALLED_APPS = [
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

if os.getenv('DB_ENGINE', 'sqlite') == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'falcon'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
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

# CSV 切片策略（v1.2 多机）：默认 False → 各 agent 拿同一份完整 CSV（字典表 / 共享
# 参数场景）；True → executor 调 scheduler.slice_csv_by_offset 按行模分片上传，
# 各 agent 只拿自己那部分（账号池等"每条数据只能用一次"场景）。
# 开发态 .env 设 CSV_SLICE_ENABLED=true 开启。粒度暂时全 task 全 binding；
# per-binding 控制留到将来给 TaskCsvBinding 加字段。
CSV_SLICE_ENABLED = os.getenv('CSV_SLICE_ENABLED', '').lower() == 'true'
