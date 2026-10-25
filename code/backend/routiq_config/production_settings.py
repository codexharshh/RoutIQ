import os
from django.core.exceptions import ImproperlyConfigured
from .settings import *

# Production settings
DEBUG = False

# Hosted containers must use a durable PostgreSQL database. Never silently
# fall back to SQLite in a production environment.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise ImproperlyConfigured(
        "DATABASE_URL is required in production; configure the hosted PostgreSQL connection."
    )

def required_csv(name: str) -> list[str]:
    values = [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]
    if not values:
        raise ImproperlyConfigured(f"{name} must contain at least one configured value.")
    if any("*" in value for value in values):
        raise ImproperlyConfigured(f"{name} must use explicit allowlist entries; wildcards are not permitted.")
    return values


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", os.environ.get("SECRET_KEY", "")).strip()
if len(SECRET_KEY) < 50 or SECRET_KEY.lower().startswith("replace-with-"):
    raise ImproperlyConfigured("Configure a strong production DJANGO_SECRET_KEY (at least 50 characters).")

ALLOWED_HOSTS = required_csv("DJANGO_ALLOWED_HOSTS")
CORS_ALLOWED_ORIGINS = required_csv("DJANGO_CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = required_csv("DJANGO_CSRF_TRUSTED_ORIGINS")
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = False

# Require HTTPS redirection by default; override only for a known local TLS terminator.
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "true").strip().lower() in {"1", "true", "yes"}
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

# The shared settings module handles DATABASE_URL with enforced SSL and bounded
# connection settings. The legacy government database alias remains unchanged.

# Email settings for production
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'admin@potholetracker.com')

# Static files for production
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Serve React app at root
WHITENOISE_INDEX_FILE = True
WHITENOISE_USE_FINDERS = True

# WhiteNoise middleware
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Additional CORS headers
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]
