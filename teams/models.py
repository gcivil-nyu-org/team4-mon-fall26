from django.conf import settings
from django.db import models


class Season(models.Model):
    """Minimal season. Will grow when league scheduling is built."""

    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    max_roster_size = models.PositiveSmallIntegerField(
        default=12, help_text="Most players a team in this season can have."
    )

    def __str__(self):
        return self.name


class Team(models.Model):
    # Cap for teams that are not in a season.
    DEFAULT_MAX_ROSTER_SIZE = 12

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

    @property
    def max_roster_size(self):
        if self.season:
            return self.season.max_roster_size
        return self.DEFAULT_MAX_ROSTER_SIZE

    def is_full(self):
        return self.roster.count() >= self.max_roster_size


def season_team_for(player, season):
    """The team the player is on in this season, or None. Teams with no season don't count."""
    if season is None:
        return None
    entry = (
        Roster.objects.filter(player=player, team__season=season)
        .select_related("team")
        .first()
    )
    return entry.team if entry else None


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


class FreeAgentRequest(models.Model):
    """A verified player asking a League Admin for placement in a season."""

    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="free_agent_requests",
    )
    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name="free_agent_requests",
    )
    sport = models.CharField(max_length=50)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["requested_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "season"], name="unique_free_agent_request_per_season"
            )
        ]

    def __str__(self):
        return f"{self.player} seeking placement in {self.season}"
