"""
Django settings for heatstress project.
热应激预警系统 - 大屏指挥中心
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# 高德地图API配置
AMAP_KEY = 'd9d1c7a2f24e696537efad04678f1db9'
AMAP_SECRET = '64f4e4427165581672bcbfde773e390a'

SECRET_KEY = 'django-insecure-heat-stress-warning-system-2026!'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # 静态文件服务（Gunicorn 环境必需）
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'heatstress.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'heatstress.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'

# ═══════════════════════════════════════════════════════════
# 中继服务器 & watch-api 转发配置
# ═══════════════════════════════════════════════════════════

# 中继服务器 SSH (39.105.86.77:22)
RELAY_HOST = '39.105.86.77'
RELAY_USER = 'root'
RELAY_PASSWORD = 'PPSUC_2026'

# MQTT (EMQX) 连接配置 — 大屏端直连中继服务器
MQTT_BROKER = os.environ.get('MQTT_BROKER', '39.105.86.77')
MQTT_PORT = int(os.environ.get('MQTT_PORT', '1883'))
MQTT_USERNAME = os.environ.get('MQTT_USERNAME', '')
MQTT_PASSWORD = os.environ.get('MQTT_PASSWORD', '')
MQTT_WORKER_COUNT = int(os.environ.get('MQTT_WORKER_COUNT', '2'))
MQTT_QUEUE_SIZE = int(os.environ.get('MQTT_QUEUE_SIZE', '2000'))

# watch-api 转发 — 已改为直连 MQTT，不再需要 HTTP 转发
# 核心温度由中继 bridge.py 调用模型 API 计算后，通过 MQTT 下发
WATCH_API_FORWARD_ENABLED = os.environ.get('WATCH_API_FORWARD_ENABLED', 'false').lower() == 'true'
WATCH_API_URL = os.environ.get('WATCH_API_URL', '')

# ═══════════════════════════════════════════════════════════
# 手表 MAC 地址白名单（5 个手表，暂未确定具体 MAC）
# ═══════════════════════════════════════════════════════════
WATCH_MAC_LIST = [
    # 'AA:BB:CC:DD:EE:01',
    # 'AA:BB:CC:DD:EE:02',
    # 'AA:BB:CC:DD:EE:03',
    # 'AA:BB:CC:DD:EE:04',
    # 'AA:BB:CC:DD:EE:05',
]

# 本地数据缓存目录（CSV 导出等）
DATA_CACHE_DIR = BASE_DIR / 'data_cache'

# 缓存最大保留时间（秒）
CACHE_MAX_AGE_SECONDS = 3600  # 1 小时
