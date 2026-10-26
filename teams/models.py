from django.conf import settings
from django.db import models


class Season(models.Model):
    """Minimal season. Will grow when league scheduling is built."""

    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Team(models.Model):
    name = models.CharField(max_length=100)
    sport = models.CharField(max_length=50)
    season = models.ForeignKey(
        Season, null=True, blank=True, on_delete=models.SET_NULL, related_name="teams"
    )
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="captained_teams",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "season"], name="unique_team_name_per_season"
            )
        ]

    def __str__(self):
        return self.name


class Roster(models.Model):
    """One row per player on a team."""

    class Role(models.TextChoices):
        CAPTAIN = "captain", "Captain"
        PLAYER = "player", "Player"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="roster")
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="roster_entries",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.PLAYER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "player"], name="unique_player_per_team"
            )
        ]

    def __str__(self):
        return f"{self.player} on {self.team} ({self.role})"
