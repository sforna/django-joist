from django.apps import AppConfig


class JoistConfig(AppConfig):
    name = "django_joist"
    label = "joist"
    verbose_name = "Joist"

    def ready(self) -> None:
        # Import for its @receiver registration; kept lazy so the app works
        # before settings are fully loaded.
        from . import signals  # noqa: F401
