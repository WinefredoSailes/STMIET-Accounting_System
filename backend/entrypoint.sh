#!/bin/sh
# Render container entrypoint (see render.yaml dockerCommand / ADR-040).
# Runs migrations, gathers static files, then serves the app. Idempotent — safe
# to run on every deploy.

set -e

echo "==> Applying database migrations (--run-sync)"
python manage.py migrate --run-sync --noinput

echo "==> Collecting static files"
python manage.py collectstatic --noinput

echo "==> Starting gunicorn (web)"
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000