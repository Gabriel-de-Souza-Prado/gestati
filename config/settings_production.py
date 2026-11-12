"""Hospedagem HTTPS no Render, separada da configuração local de desenvolvimento."""
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

if not os.environ.get("GESTATI_SECRET_KEY"):
    raise ImproperlyConfigured("Configure GESTATI_SECRET_KEY no ambiente da hospedagem.")
if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured("Configure DATABASE_URL para o PostgreSQL da hospedagem.")

from .settings import *  # noqa: F403,E402

DEBUG = False
SECRET_KEY = os.environ["GESTATI_SECRET_KEY"]
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("GESTATI_ALLOWED_HOSTS", "").split(",") if h.strip()]
hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if hostname and hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(hostname)
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Configure o domínio da hospedagem, sem liberar todos os hosts.")
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]

try:
    database = dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=60, conn_health_checks=True)
except (ValueError, TypeError):
    raise ImproperlyConfigured("DATABASE_URL inválida. Confira a configuração no painel, sem divulgá-la.") from None
if database["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("A hospedagem do GESTATI exige PostgreSQL.")
database.setdefault("OPTIONS", {})["connect_timeout"] = 5
DATABASES = {"default": database}

MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# O proxy HTTPS do Render informa o protocolo original da requisição.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = 3600
# Não solicitar preload nem impor política a subdomínios nesta demonstração.
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
