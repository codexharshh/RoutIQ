"""RoutIQ Gunicorn configuration with deployment-specific settings via environment."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.environ.get("ROUTIQ_LOG_DIR", BACKEND_DIR / "logs")).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)

workers = int(os.environ.get("ROUTIQ_GUNICORN_WORKERS", "4"))
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
preload_app = True
timeout = int(os.environ.get("ROUTIQ_GUNICORN_TIMEOUT", "30"))
keepalive = 2
worker_tmp_dir = os.environ.get("ROUTIQ_GUNICORN_WORKER_TMP_DIR", "/dev/shm")
syslog = False
bind = os.environ.get("ROUTIQ_GUNICORN_BIND", "127.0.0.1:8000")
umask = 0
loglevel = os.environ.get("ROUTIQ_GUNICORN_LOG_LEVEL", "info")
user = os.environ.get("ROUTIQ_GUNICORN_USER") or None
group = os.environ.get("ROUTIQ_GUNICORN_GROUP") or None
accesslog = str(LOG_DIR / "gunicorn_access.log")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%({X-Real-IP}i)s"'
errorlog = str(LOG_DIR / "gunicorn_error.log")
