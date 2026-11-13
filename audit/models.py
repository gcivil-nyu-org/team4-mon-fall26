from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """One row per League Admin change to a Team, Season, Sport, Match or Facility."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        help_text="Who made the change. Empty for shell or seed-script changes.",
    )
    action = models.CharField(max_length=10, choices=Action.choices, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    object_type = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=50)
    object_repr = models.CharField(max_length=200)

    class Meta:
        ordering = ["-timestamp", "-pk"]

    def __str__(self):
        by = self.actor or "system"
        return f"{self.action} {self.object_type} {self.object_id} by {by}"
