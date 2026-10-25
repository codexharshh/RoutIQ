# syntax=docker/dockerfile:1

# Build the existing React + TypeScript application without changing its source.
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app/code
COPY code/package.json code/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY code/ ./
RUN npm run build

# Runtime image: Django remains the system of record; FastAPI stays loopback-only.
FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_ENVIRONMENT=production \
    DJANGO_DEBUG=false \
    PYTHONPATH=/app/code/backend \
    ROUTIQ_DETECTOR_BACKEND=ultralytics \
    ROUTIQ_MODEL_WEIGHTS=/app/code/backend/models/yolov8s_seed0_best.pt \
    ROUTIQ_DETECTOR_DEVICE=cpu

WORKDIR /app

# Runtime libraries needed by OpenCV, OCR, image processing, Nginx and Supervisor.
RUN apt-get update && apt-get install -y --no-install-recommends \
      nginx supervisor tesseract-ocr libgl1 libglib2.0-0 libgomp1 \
      libsm6 libxext6 libxrender1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY code/backend/ /app/code/backend/
COPY --from=frontend-build /app/code/dist/ /app/code/dist/

WORKDIR /app/code/backend

# Download the attributed RDD2022 checkpoint and verify its published SHA-256.
# The model is fetched at build time; no model binary or credentials are committed.
RUN mkdir -p /app/code/backend/models \
    && curl -fL --retry 3 --retry-delay 2 \
      "https://huggingface.co/SreekarAditya/yolo-rdd2022-benchmark/resolve/main/yolov8s_seed0_best.pt?download=true" \
      -o /app/code/backend/models/yolov8s_seed0_best.pt \
    && echo "565aae6915e34e4f7f4c44dac0bdcf9fff21b83c4adc74cc97ca09cc31882ce8  /app/code/backend/models/yolov8s_seed0_best.pt" | sha256sum -c - \
    && pip install --no-cache-dir . "psycopg2-binary>=2.9.9" \
    && mkdir -p /var/www/routiq /var/log/supervisor /run/nginx

# Keep the public UI and Django API on the same origin. FastAPI is not exposed
# through Nginx and listens only on 127.0.0.1 inside this container.
RUN cat > /etc/nginx/sites-available/default <<'NGINX'
server {
    listen 0.0.0.0:10000;
    server_name _;
    client_max_body_size 100m;

    root /app/code/dist;
    index index.html;

    location = /healthz {
        access_log off;
        add_header Content-Type text/plain;
        return 200 "ok";
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /gov-api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /accounts/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /admin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /media/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
    }

    location = /index.html {
        root /app/code/dist;
    }

    location ^~ /project/routiq/ {
        rewrite ^/project/routiq/(.*)$ /$1 break;
        try_files $uri $uri/ /index.html;
    }

    location /assets/ {
        try_files $uri =404;
    }

    location = / {
        return 302 /project/routiq/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
NGINX

RUN cat > /etc/supervisor/conf.d/routiq.conf <<'SUPERVISOR'
[supervisord]
nodaemon=true
user=root
logfile=/dev/null
pidfile=/run/supervisord.pid

[program:fastapi]
directory=/app/code/backend
command=uvicorn fastapi_service.main:app --host 127.0.0.1 --port 8100
autostart=true
autorestart=true
priority=10
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:django]
directory=/app/code/backend
command=gunicorn routiq_config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 120
autostart=true
autorestart=true
priority=20
environment=ROUTIQ_VISION_URL="http://127.0.0.1:8100"
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:nginx]
command=/usr/sbin/nginx -g "daemon off;"
autostart=true
autorestart=true
priority=30
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
SUPERVISOR

# Render's web service must provide a persistent database via DATABASE_URL and
# secrets through environment variables. Never bake credentials into this image.
EXPOSE 10000
CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate --noinput && exec /usr/bin/supervisord -c /etc/supervisor/conf.d/routiq.conf"]
