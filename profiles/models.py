from django.conf import settings
from django.db import models


class PlayerProfile(models.Model):
    """One row per user. Holds the NYU identifiers the user edits on their profile."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="player_profile",
    )
    # Nullable so profiles that haven't been filled in yet don't clash on uniqueness.
    n_number = models.CharField(
        "N number",
        max_length=9,
        unique=True,
        null=True,
        blank=True,
        error_messages={"unique": "This N number is already used by another account."},
    )
    net_id = models.CharField(
        "NetID",
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        error_messages={"unique": "This NetID is already used by another account."},
    )

    def __str__(self):
        return f"Profile of {self.user}"
