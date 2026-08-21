#!/bin/bash
set -e

cd /app

# Synchronize the production database schema before serving requests.
# Already-applied Alembic revisions are a no-op.
flask --app run:app db upgrade

exec gunicorn \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 2 \
  --timeout 900 \
  --log-level=debug \
  run:app
