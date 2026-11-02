from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .catalog_rules import name_key, validate_catalog_name


class Sport(models.Model):
    """A sport available for teams and events."""

    name = models.CharField(max_length=50, unique=True)

    def clean(self):
        try:
            self.name = validate_catalog_name(self.name or "")
        except ValidationError as exc:
            raise ValidationError({"name": exc.messages})

        for sport in Sport.objects.exclude(pk=self.pk).only("name"):
            if name_key(sport.name) == name_key(self.name):
                raise ValidationError(
                    {"name": "A sport with this name already exists."}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class EventType(models.Model):
    """An event type belonging to one sport."""

    sport = models.ForeignKey(
        Sport,
        on_delete=models.CASCADE,
        related_name="event_types",
    )
    name = models.CharField(max_length=50)

    def clean(self):
        try:
            self.name = validate_catalog_name(self.name or "")
        except ValidationError as exc:
            raise ValidationError({"name": exc.messages})

        if self.sport_id:
            for event_type in (
                EventType.objects.filter(sport_id=self.sport_id)
                .exclude(pk=self.pk)
                .only("name")
            ):
                if name_key(event_type.name) == name_key(self.name):
                    raise ValidationError(
                        {
                            "name": (
                                "An event type with this name already "
                                "exists for this sport."
                            )
                        }
                    )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sport.name} - {self.name}"


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


class Division(models.Model):
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="divisions"
    )
    name = models.CharField(max_length=50)
    name_key = models.CharField(max_length=150, editable=False)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["season", "name_key"], name="unique_division_name_per_season"
            )
        ]

    def clean(self):
        self.name = validate_catalog_name(self.name)
        self.name_key = name_key(self.name)
        if (
            self.season_id
            and type(self)
            .objects.filter(season_id=self.season_id, name_key=self.name_key)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                {"name": "A division with this name already exists in this season."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Team(models.Model):
    # Cap for teams that are not in a season.
    DEFAULT_MAX_ROSTER_SIZE = 12

    name = models.CharField(max_length=100)
    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="teams",
    )
    season = models.ForeignKey(
        Season, null=True, blank=True, on_delete=models.SET_NULL, related_name="teams"
    )
    division = models.ForeignKey(
        Division,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="teams",
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

    def clean(self):
        if self.division_id and (
            self.season_id is None or self.division.season_id != self.season_id
        ):
            raise ValidationError(
                {"division": "Choose a division from this team's season."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

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
    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="free_agent_requests",
    )

    division = models.ForeignKey(
        Division,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="free_agent_requests",
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["requested_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "season"], name="unique_free_agent_request_per_season"
            )
        ]

    def clean(self):
        if self.division_id and self.division.season_id != self.season_id:
            raise ValidationError(
                {"division": "Choose a division from the requested season."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.player} seeking placement in {self.season}"
