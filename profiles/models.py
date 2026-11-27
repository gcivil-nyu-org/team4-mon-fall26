from django.conf import settings
from django.db import models

from core.names import display_name


class PlayerProfile(models.Model):
    """One row per user. Holds the NYU identifiers the user edits on their profile."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="player_profile",
    )
    # Not unique: PlayNYU can't check whose N number it is, so one user's entry
    # must not block another's (#304). Only the owner sees it.
    n_number = models.CharField("N number", max_length=9, null=True, blank=True)
    # Nullable so profiles that haven't been filled in yet don't clash on uniqueness.
    net_id = models.CharField(
        "NetID",
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        error_messages={"unique": "This NetID is already used by another account."},
    )
    # Off leaves the player out of the player leaderboards (#311).
    show_on_leaderboards = models.BooleanField(
        "Show me on leaderboards",
        default=True,
        help_text="Untick to leave your name out of the player leaderboards.",
    )

    def __str__(self):
        return f"Profile of {display_name(self.user)}"
