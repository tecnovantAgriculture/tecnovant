#!/bin/bash
cd /app
pip install --no-cache-dir -r requirements.txt
# nohup gunicorn --bind 0.0.0.0:5080 --workers 2  --log-level=debug --reload run:app > log.txt 2>&1 &
nohup gunicorn --bind 0.0.0.0:5080 --workers 2 --timeout 300 --log-level=debug --reload run:app > log.txt 2>&1 &
# Necessary to keep the container running
tail -f log.txt

# Producción 
# nohup gunicorn run:app \
#   --bind 0.0.0.0:5080 \
#   --workers 4 \
#   --worker-class gevent \
#   --worker-connections 1000 \
#   --timeout 240 \
#   --log-level=info \
#   > log.txt 2>&1 &


# Producción 2
# nohup gunicorn run:app \
#   --bind 0.0.0.0:5080 \
#   --workers 4 \
#   --threads 2 \
#   --worker-connections 1000 \
#   --max-requests 1000 \
#   --max-requests-jitter 100 \
#   --preload-app \
#   --timeout 300 \
#   --log-level=info > log.txt 2>&1 &

