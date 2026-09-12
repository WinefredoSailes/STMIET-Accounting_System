"""Postgres smoke-test settings: real DATABASE_URL backend (parsed by
config.settings.base via django-environ), lightweight like test.py elsewhere.

Run target: pytest apps/ui/test_postgres_smoke.py -o addopts="" --migrations
with DATABASE_URL pointing at a Postgres instance the connecting role can
CREATE DATABASE on (pytest creates a test_* database).
"""

from .base import *  # noqa: F401,F403

DEBUG = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LOGGING = {}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CELERY_TASK_ALWAYS_EAGER = True