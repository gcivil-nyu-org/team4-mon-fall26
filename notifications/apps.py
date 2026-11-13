from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        # Receivers live in this app only (never in matches/ or core/),
        # so importing here keeps sibling apps untouched.
        from . import signals  # noqa: F401
