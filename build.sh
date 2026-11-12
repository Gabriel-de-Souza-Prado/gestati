#!/usr/bin/env bash
set -euo pipefail
export DJANGO_SETTINGS_MODULE=config.settings_production
: "${DATABASE_URL:?Configure o banco separado da hospedagem.}"
: "${GESTATI_SECRET_KEY:?Configure a chave da hospedagem.}"

python -m pip install -r requirements-render.txt
python manage.py collectstatic --noinput
