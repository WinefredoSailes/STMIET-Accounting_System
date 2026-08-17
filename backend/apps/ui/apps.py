from django.apps import AppConfig


class UiConfig(AppConfig):
    """Server-rendered UI (Django templates + HTMX + Tailwind).

    HTML views only; all business logic stays in the bounded-context
    services. This app never defines domain models.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ui"
    verbose_name = "UI (server-rendered screens)"
