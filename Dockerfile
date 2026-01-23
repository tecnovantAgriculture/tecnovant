FROM python:3.10-slim
# FROM pypy:latest
WORKDIR /app

# OS deps (Expat)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libexpat1 \
 && rm -rf /var/lib/apt/lists/*

COPY project/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY project/start.sh .
RUN chmod +x start.sh
CMD ["./start.sh"]

