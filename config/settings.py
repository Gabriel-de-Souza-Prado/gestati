"""Configuração inicial para desenvolvimento local com PostgreSQL."""
import json
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONFIG_PATH = BASE_DIR / ".gestati.local.json"

try:
    LOCAL_CONFIG = (
        json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
        if LOCAL_CONFIG_PATH.exists()
        else {}
    )
except (OSError, json.JSONDecodeError):
    raise ImproperlyConfigured(
        "Não foi possível ler a configuração local do GESTATI."
    ) from None

if not isinstance(LOCAL_CONFIG, dict):
    raise ImproperlyConfigured("A configuração local deve ser um objeto JSON.")

SECRET_KEY = os.environ.get("GESTATI_SECRET_KEY") or LOCAL_CONFIG.get("secret_key")
if not isinstance(SECRET_KEY, str) or not SECRET_KEY:
    raise ImproperlyConfigured(
        "Execute o configurar_ambiente.py com o Python da .venv antes de iniciar."
    )

DEBUG = os.environ.get("GESTATI_DEBUG", "true").lower() in {"true", "1", "yes"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "GESTATI_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]"
    ).split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "contas.apps.ContasConfig",
    "core.apps.CoreConfig",
    "cadastros.apps.CadastrosConfig",
    "estoque.apps.EstoqueConfig",
    "ativos.apps.AtivosConfig",
    "ordens.apps.OrdensConfig",
    "movimentacoes.apps.MovimentacoesConfig",
    "baixas.apps.BaixasConfig",
    "relatorios.apps.RelatoriosConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "contas.middleware.TrocaSenhaObrigatoriaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("GESTATI_DB_NAME", "gestati"),
        "USER": os.environ.get("GESTATI_DB_USER", "gestati_app"),
        "PASSWORD": os.environ.get("GESTATI_DB_PASSWORD")
        or LOCAL_CONFIG.get("db_password", ""),
        "HOST": os.environ.get("GESTATI_DB_HOST", "localhost"),
        "PORT": os.environ.get("GESTATI_DB_PORT", "5432"),
        "OPTIONS": {"connect_timeout": 5},
    }
}

AUTH_USER_MODEL = "contas.Usuario"
AUTHENTICATION_BACKENDS = [
    "contas.backends.UsuarioSemDiferencaDeCaixaBackend",
    # Preserva sessões existentes; novas autenticações passam pelo primeiro.
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
