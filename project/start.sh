#!/bin/bash
set -e

cd /app

exec gunicorn \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 2 \
  --timeout 300 \
  --log-level=debug \
  --reload \
  run:app
