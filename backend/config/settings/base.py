"""
Base settings for the STMIET Accounting System.

Architecture principles (see /docs/adr):
- ADR-010: Django modular monolith, PostgreSQL, environment-driven config (12-factor).
- Every environment-specific value comes from the environment (.env), never hardcoded.
- Apps are organized by bounded context under apps/ (ADR-009).
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, ""),
    ALLOWED_HOSTS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
    DATABASE_URL=(str, "sqlite:///db.sqlite3"),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    TIME_ZONE=(str, "Asia/Manila"),
    JE_APPROVAL_THRESHOLD=(str, "100000.00"),
)

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
]

# Bounded contexts, in dependency order (ADR-009).
DOMAIN_APPS = [
    "apps.core",
    "apps.foundation",    # COA, segments, fiscal calendar (Phase 1)
    "apps.sequences",     # document number registry (Phase 1)
    "apps.workflow",      # approval/state machine (Phase 1)
    "apps.posting",       # journal engine, GL, posting rules (Phase 1)
    "apps.ar",            # receivables (Phase 2)
    "apps.ap",            # payables (Phase 3)
    "apps.cash",          # banks, petty cash, reconciliation (Phase 4)
    "apps.inventory",     # inventory integration (Phase 5)
    "apps.fleet",         # fleet/fuel bridge (Phase 5)
    "apps.payroll",       # payroll GL feed (Phase 6)
    "apps.assets",        # fixed assets (Phase 7)
    "apps.tax",           # VAT, WHT, BIR (Phase 9)
    "apps.reporting",     # financial statements (Phase 8)
    "apps.ui",            # server-rendered UI (templates + HTMX, no models)
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + DOMAIN_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.ui.context_processors.pending_approval_count",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# DATABASE_URL drives the engine. SQLite is the zero-config dev fallback;
# PostgreSQL is the reference target (ADR-010).

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

# SQLite tuning (dev fallback). Transactions are scoped per service mutation
# (see @transaction.atomic + @retry_on_lock in apps.ap.services), NOT per
# request: with ATOMIC_REQUESTS every GET held a WAL read snapshot for the
# whole request, so a concurrent writer could fail instantly with
# SQLITE_BUSY_SNAPSHOT — which bypasses busy_timeout and produced the
# 'database is locked' 500s on approve/sign/clear. WAL + a long
# busy_timeout still make plain writers wait for the lock instead of erroring.
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 30

from django.db.backends.signals import connection_created  # noqa: E402
from django.dispatch import receiver  # noqa: E402


@receiver(connection_created)
def _tune_sqlite(sender, connection, **kwargs):  # noqa: ARG001
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")

# ---------------------------------------------------------------------------
# Auth / password validation
# ---------------------------------------------------------------------------

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static / media
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# REST Framework (ADR-010 API-first; SimpleJWT auth)
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "STMIET Accounting System API",
    "DESCRIPTION": "General ledger, AR/AP, treasury, payroll feed, and reporting for "
    "Seven-Trent Machineries Industrial Equipment Trading (ADR-009/010).",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# ---------------------------------------------------------------------------
# Domain constants (seeded via management commands; overridable in .env)
# ---------------------------------------------------------------------------

DOMAIN = {
    # ADR-033: JE approval threshold before a second reviewer is required.
    "JE_APPROVAL_THRESHOLD": env("JE_APPROVAL_THRESHOLD"),
    # ADR-013: default accounting cycle = Tuesday to Monday.
    "CYCLE_START_DAY": env.int("CYCLE_START_DAY", default=1),  # 0=Mon..6=Sun; 1=Tue
    "CYCLE_END_DAY": env.int("CYCLE_END_DAY", default=0),      # 0=Mon
    # ADR-032: petty cash replenishment trigger (85% of fund consumed).
    "PCF_REPLENISH_TRIGGER": env.float("PCF_REPLENISH_TRIGGER", default=0.85),
    # ADR-020/033: COO (CNR) review gate. Off during UAT — the Accounting &
    # Finance Head approves every amount; flip on at go-live to require the
    # COO above CNR_ESCALATION_THRESHOLD again.
    "COO_REVIEW_ENABLED": env.bool("COO_REVIEW_ENABLED", default=False),
    # ADR-018: auto-place fully-approved RFPs into an open CONSO batch when
    # they complete approval (reversible — flip off for manual batching).
    "CONSO_AUTO_ASSIGN": env.bool("CONSO_AUTO_ASSIGN", default=False),
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{levelname}] {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apps.posting": {"level": "INFO"},
        "django.request": {"level": "WARNING"},
    },
}
