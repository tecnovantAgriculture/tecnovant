#!/bin/bash
cd /app
pip install --no-cache-dir -r requirements.txt
# nohup gunicorn --bind 0.0.0.0:5080 --workers 2  --log-level=debug --reload run:app > log.txt 2>&1 &
nohup gunicorn --bind 0.0.0.0:5080 --workers 2 --timeout 300 --log-level=debug --reload run:app > log.txt 2>&1 &
# Necessary to keep the container running
tail -f log.txt
