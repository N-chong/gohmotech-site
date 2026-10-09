from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'
    verbose_name = 'Dashboard'

    def ready(self):
        # Importing registers authentication signal receivers once Django's app
        # registry is ready.
        from . import signals  # noqa: F401
