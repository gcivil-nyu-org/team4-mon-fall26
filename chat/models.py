from django.conf import settings
from django.db import models


class Message(models.Model):
    """One chat message on a team's thread."""

    MAX_BODY_LENGTH = 500

    team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="chat_messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    body = models.CharField(max_length=MAX_BODY_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    is_flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.author} on {self.team}: {self.body[:40]}"


class ThreadRead(models.Model):
    """When one player last read one team's thread."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_thread_reads",
    )
    team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="chat_thread_reads"
    )
    last_read_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "team"], name="unique_thread_read_per_user_team"
            )
        ]

    def __str__(self):
        return f"{self.user} read {self.team} at {self.last_read_at:%Y-%m-%d %H:%M}"
