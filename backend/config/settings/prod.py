"""Production settings: strict security, PostgreSQL required, no debug."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Production must target PostgreSQL only.
_db = env.db("DATABASE_URL")
if _db["ENGINE"] != "django.db.backends.postgresql":
    raise RuntimeError("DATABASE_URL must point to PostgreSQL in production.")