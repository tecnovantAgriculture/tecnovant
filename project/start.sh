#!/bin/bash
set -e

cd /app

# Synchronize the production database schema before serving requests.
# Already-applied Alembic revisions are a no-op.
flask --app run:app db upgrade

exec gunicorn \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 1 \
  --max-requests 100 \
  --max-requests-jitter 20 \
  --timeout 900 \
  --log-level=debug \
  run:app
