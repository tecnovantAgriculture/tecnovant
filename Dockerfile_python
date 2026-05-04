FROM python:3.10-slim
# FROM pypy:latest
WORKDIR /app
COPY project/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY project/start.sh .
RUN chmod +x start.sh
CMD ["./start.sh"]

