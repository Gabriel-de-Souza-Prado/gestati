#!/usr/bin/env bash
set -euo pipefail
export DJANGO_SETTINGS_MODULE=config.settings_production
: "${DATABASE_URL:?Configure o banco separado da hospedagem.}"
: "${GESTATI_SECRET_KEY:?Configure a chave da hospedagem.}"

# Executados no ambiente da demonstração, nunca no banco local do desenvolvedor.
python manage.py migrate --noinput
python manage.py inicializar_admin
exec python -m gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 2 --timeout 120
