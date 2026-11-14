from django.conf import settings
from django.db import models


class RateLimitBucket(models.Model):
    """A short-lived, shared counter for authentication and email throttles.

    The key is an HMAC of the limit type and identifier, so the database never
    stores a raw email address or IP address.
    """

    bucket_key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(db_index=True)


class PendingAccount(models.Model):
    """Marks a placeholder user that someone added before the person signed up.

    The row exists while the placeholder is unclaimed. Opening the email link
    after sign-up deletes it.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="pending_account",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pending: {self.user.email}"
