from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from .catalog_rules import name_key, validate_catalog_name
from .season_rules import (
    SeasonState,
    automatic_states,
    season_allows,
    validate_registration_date,
    validate_season_dates,
    validate_transition,
)


class SeasonQuerySet(models.QuerySet):
    def allowing(self, action):
        """Seasons whose state allows the action (see SeasonAction)."""
        states = [state for state in SeasonState.values if season_allows(state, action)]
        return self.filter(state__in=states)

    def visible_to_players(self):
        """Draft seasons are still being set up, so players don't see them."""
        return self.exclude(state=SeasonState.DRAFT)


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
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    state = models.CharField(
        max_length=10, choices=SeasonState.choices, default=SeasonState.DRAFT
    )
    registration_closes_on = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Teams can register until this date. "
            "On the next day the season becomes active."
        ),
    )
    auto_state = models.BooleanField(
        default=True,
        verbose_name="Change state automatically by date",
        help_text=(
            "The season becomes active after registration closes, "
            "and closed after the end date."
        ),
    )
    max_roster_size = models.PositiveSmallIntegerField(
        default=12, help_text="Most players a team in this season can have."
    )
    # Blank means any sport: custom leagues and seasons made before sports.
    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="seasons",
        help_text="Teams in this season must play this sport. Leave blank for any.",
    )
    # Set only on default semester seasons, for example "2026-fall".
    term = models.CharField(max_length=20, blank=True, editable=False)

    objects = SeasonQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sport", "term"],
                condition=~models.Q(term=""),
                name="unique_default_season_per_sport_term",
            )
        ]

    def clean(self):
        if self.start_date:
            validate_season_dates(self.start_date, self.end_date)
        validate_registration_date(self.registration_closes_on, self.end_date)

    def automatic_states(self, today):
        """The states advance_season_states moves this season through on `today`."""
        return automatic_states(
            self.state,
            self.auto_state,
            self.registration_closes_on,
            self.end_date,
            today,
        )

    def allows(self, action):
        return season_allows(self.state, action)

    def move_to(self, target):
        """Change state along ALLOWED_TRANSITIONS; raises ValidationError otherwise."""
        validate_transition(self.state, target)
        self.state = target
        self.save(update_fields=["state"])

    def sport_mismatch(self, sport_id, subject="Teams", verb="play"):
        """The error for a team or request of another sport, or None if it fits."""
        if self.sport_id is None or sport_id is None or sport_id == self.sport_id:
            return None
        return f"{subject} in {self.name} must {verb} {self.sport.name}."

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
        errors = {}
        if self.division_id and (
            self.season_id is None or self.division.season_id != self.season_id
        ):
            errors["division"] = "Choose a division from this team's season."
        if self.season_id:
            mismatch = self.season.sport_mismatch(self.sport_id)
            if mismatch:
                errors["sport"] = mismatch
        if errors:
            raise ValidationError(errors)
        self._validate_season_change()

    def _validate_season_change(self):
        """A team takes its roster with it, so the new season's rules must hold."""
        if self.pk is None:
            return
        stored = Team.objects.filter(pk=self.pk).values_list("season_id", flat=True)
        if not stored or stored[0] == self.season_id:
            return

        roster = Roster.objects.filter(team_id=self.pk)
        if roster.count() > self.max_roster_size:
            raise ValidationError(
                {
                    "season": (
                        f"This team has too many players for that season "
                        f"({self.max_roster_size} at most)."
                    )
                }
            )
        if (
            self.season_id is not None
            and Roster.objects.filter(
                team__season_id=self.season_id, player__in=roster.values("player")
            ).exists()
        ):
            raise ValidationError(
                {
                    "season": (
                        "A player on this team is already on another team "
                        "in that season."
                    )
                }
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

    def allows(self, action):
        """Season rules only apply to teams in a season."""
        return self.season is None or self.season.allows(action)


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

    def clean(self):
        """Roster capacity and one team per season, for every way onto a team."""
        if not (self.team_id and self.player_id):
            return

        stored = None
        if self.pk:
            stored = (
                Roster.objects.filter(pk=self.pk).values("team_id", "player_id").first()
            )
        new_to_team = stored is None or stored["team_id"] != self.team_id
        # Editing a row in place (its role, say) isn't joining, so rosters left
        # over the limit by a lower cap can still be edited.
        if not new_to_team and stored["player_id"] == self.player_id:
            return

        others = Roster.objects.exclude(pk=self.pk)
        if (
            new_to_team
            and others.filter(team_id=self.team_id).count() >= self.team.max_roster_size
        ):
            raise ValidationError(
                f"The roster is full ({self.team.max_roster_size} players)."
            )
        if (
            self.team.season_id is not None
            and others.filter(
                player_id=self.player_id, team__season_id=self.team.season_id
            )
            .exclude(team_id=self.team_id)
            .exists()
        ):
            # Don't name the other team: whoever is adding may not be allowed to see it.
            raise ValidationError("That player is already on another team this season.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            # Same lock order as the views: season, then team.
            if self.team.season_id:
                Season.objects.select_for_update().get(pk=self.team.season_id)
            Team.objects.select_for_update().get(pk=self.team_id)
            self.clean()
            super().save(*args, **kwargs)

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
        errors = {}
        if self.division_id and self.division.season_id != self.season_id:
            errors["division"] = "Choose a division from the requested season."
        if self.season_id:
            mismatch = self.season.sport_mismatch(
                self.sport_id, subject="Free agents", verb="ask for"
            )
            if mismatch:
                errors["sport"] = mismatch
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.player} seeking placement in {self.season}"
