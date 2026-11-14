from django.conf import settings
from django.db import models
from django.utils import timezone


class Topic(models.Model):
    """A forum topic, filed under one sport or under General (no sport)."""

    MAX_TITLE_LENGTH = 120
    MAX_BODY_LENGTH = 2000

    # SET_NULL: a topic outlives its sport and moves to General, so forum
    # posts never stop a League Admin from retiring a sport.
    sport = models.ForeignKey(
        "teams.Sport",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="forum_topics",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="forum_topics",
    )
    title = models.CharField(max_length=MAX_TITLE_LENGTH)
    body = models.CharField(max_length=MAX_BODY_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set on create and moved forward by each reply. Lists sort on it.
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
    # Set by a user's report. A League Admin clears it in the moderation queue.
    is_flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ["-last_activity_at", "-pk"]

    @property
    def sport_label(self):
        return self.sport.name if self.sport_id else "General"

    def __str__(self):
        return self.title


class Reply(models.Model):
    """One reply on a topic. Replies are flat: no nesting."""

    MAX_BODY_LENGTH = 1000

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="forum_replies",
    )
    body = models.CharField(max_length=MAX_BODY_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    is_flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name_plural = "replies"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            # A new reply moves its topic to the top of the forum.
            Topic.objects.filter(
                pk=self.topic_id, last_activity_at__lt=self.created_at
            ).update(last_activity_at=self.created_at)

    def __str__(self):
        return f"{self.author} on {self.topic}: {self.body[:40]}"
