"""Development settings: debug on, SQLite/Postgres fallback, local hosts."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

INSTALLED_APPS += [  # noqa: F405
    "django_extensions",
]

# Pretty SQL + auto-reload for local work.
LOGGING["root"]["level"] = "DEBUG"  # noqa: F405
