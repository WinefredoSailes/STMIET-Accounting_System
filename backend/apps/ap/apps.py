from django.apps import AppConfig


class ApConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ap'
    verbose_name = "AP (payables)"

    def ready(self):
        import apps.ap.signals  # noqa: F401

