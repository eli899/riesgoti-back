"""
Configuración central de RiesgoTI (Django 5.x + DRF + Celery + PostgreSQL).

Todas las variables sensibles se cargan desde back/.env (ver back/.env.example).
"""
import base64
import binascii
import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


# ---------------------------------------------------------------------------
# Núcleo Django
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured('La variable de entorno SECRET_KEY es obligatoria.')

DEBUG = env_bool('DEBUG', False)
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1')

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'drf_spectacular',
    'django_filters',
    'corsheaders',
    'django_celery_results',
]

LOCAL_APPS = [
    'apps.accounts',
    'apps.assets_matrix',
    'apps.ai_config',
    'apps.documents_rag',
    'apps.incidents',
    'apps.risks',
    'apps.audit',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

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
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# ---------------------------------------------------------------------------
# Base de datos PostgreSQL (esquema bd.sql)
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.environ.get('DB_NAME', 'riesgo_ti'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------
# Usuario personalizado mapeado a la tabla USUARIO de bd.sql (v0.1, MOD-01-DB-MODELS-SEEDS).
AUTH_USER_MODEL = 'accounts.Usuario'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------------------
# Internacionalización
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'es-ec'
TIME_ZONE = 'America/Guayaquil'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ---------------------------------------------------------------------------
# Django REST Framework, SimpleJWT y OpenAPI
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_THROTTLE_RATES': {
        # Mitigación de fuerza bruta en POST /api/v1/auth/login/ (ScopedRateThrottle).
        'login': os.environ.get('LOGIN_THROTTLE_RATE', '10/min'),
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'AUTH_HEADER_TYPES': ('Bearer',),
    # Claims del contrato RiesgoTI: usuario_id, nombre_completo, rol_codigo, permisos (AuthService.build_tokens).
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'usuario_id',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'RiesgoTI API',
    'DESCRIPTION': (
        'Gestión de incidencias operativas y gobierno de riesgos de Seguridad de la '
        'Información (ISO/IEC 27001, 27002 y 27005:2022).'
    ),
    'VERSION': '0.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'ENUM_NAME_OVERRIDES': {
        'ConnectionStatusEnum': ['ok', 'error'],
    },
}

# ---------------------------------------------------------------------------
# CORS (Frontend Vite)
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS', 'http://localhost:5173')

# ---------------------------------------------------------------------------
# Celery + Redis
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'django-db')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

# ---------------------------------------------------------------------------
# Almacenamiento local persistente
# ---------------------------------------------------------------------------
STORAGE_ROOT = BASE_DIR / 'storage'
PDF_STORAGE_ROOT = STORAGE_ROOT / 'pdfs'
EVIDENCE_STORAGE_ROOT = STORAGE_ROOT / 'evidences'
FAISS_INDEX_ROOT = STORAGE_ROOT / 'faiss_indices'
# Límite de carga de PDFs normativos (coincide con MAX_PDF_SIZE_BYTES de document.schema.ts).
MAX_PDF_UPLOAD_BYTES = int(os.environ.get('MAX_PDF_UPLOAD_BYTES', 25 * 1024 * 1024))
# Evidencias de incidencias (react-dropzone del portal del reportante: <= 10 MB por archivo).
MAX_EVIDENCE_BYTES = int(os.environ.get('MAX_EVIDENCE_BYTES', 10 * 1024 * 1024))
MAX_EVIDENCES_PER_INCIDENT = int(os.environ.get('MAX_EVIDENCES_PER_INCIDENT', 5))

# ---------------------------------------------------------------------------
# Workers de IA (v0.5)
# ---------------------------------------------------------------------------
LLM_TIMEOUT_SECONDS = int(os.environ.get('LLM_TIMEOUT_SECONDS', 60))
# Similitud coseno mínima para agrupar una incidencia en un RIESGO existente (independiente de umbral_similitud RAG).
RISK_GROUPING_THRESHOLD = float(os.environ.get('RISK_GROUPING_THRESHOLD', 0.75))


# ---------------------------------------------------------------------------
# Criptografía AES-256-GCM: RIESGOTI_MASTER_KEY (32 bytes en Base64)
# ---------------------------------------------------------------------------
def _load_master_key():
    raw = os.environ.get('RIESGOTI_MASTER_KEY', '').strip()
    if not raw:
        raise ImproperlyConfigured('La variable de entorno RIESGOTI_MASTER_KEY es obligatoria.')
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        try:
            key = base64.urlsafe_b64decode(raw)
        except (binascii.Error, ValueError) as exc:
            raise ImproperlyConfigured('RIESGOTI_MASTER_KEY no es Base64 válido.') from exc
    if len(key) != 32:
        raise ImproperlyConfigured(
            f'RIESGOTI_MASTER_KEY debe decodificar a 32 bytes (AES-256); se obtuvieron {len(key)}.'
        )
    return key


RIESGOTI_MASTER_KEY_BYTES = _load_master_key()
