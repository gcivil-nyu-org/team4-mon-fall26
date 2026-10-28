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
