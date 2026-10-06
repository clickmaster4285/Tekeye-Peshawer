from django.apps import AppConfig


class RequestsSupportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "requests_support"
    verbose_name = "Requests & Support"

    def ready(self):
        try:
            from . import signals  # noqa: F401
        except Exception:
            pass
