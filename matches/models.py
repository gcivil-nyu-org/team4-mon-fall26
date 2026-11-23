from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.roles import SCOREKEEPER_ROLE, users_with_role
from core.names import display_name
from facilities.models import Facility
from teams.season_rules import SeasonAction, SeasonState, season_allows


def _live_season_states():
    """Season states that allow scheduling, so their matches can still be scored."""
    return [
        state
        for state in SeasonState.values
        if season_allows(state, SeasonAction.SCHEDULE_MATCH)
    ]


class MatchQuerySet(models.QuerySet):
    def scheduled(self):
        return self.filter(status=Match.Status.SCHEDULED)

    def unscored(self):
        """Scheduled matches with no result in a live season, at any time."""
        return self.scheduled().filter(
            models.Q(home_score__isnull=True) | models.Q(away_score__isnull=True),
            season__state__in=_live_season_states(),
        )

    def overlapping(self, facility, starts_at, ends_at):
        """Scheduled matches at a facility that share time with a window.

        A match ending exactly when the window starts, or starting exactly when
        it ends, doesn't overlap it.
        """
        return self.scheduled().filter(
            facility=facility, starts_at__lt=ends_at, ends_at__gt=starts_at
        )

    def team_overlapping(self, teams, starts_at, ends_at):
        """Scheduled matches of any of `teams` that share time with a window.

        The time rule is the same as overlapping().
        """
        return self.scheduled().filter(
            models.Q(home_team__in=teams) | models.Q(away_team__in=teams),
            starts_at__lt=ends_at,
            ends_at__gt=starts_at,
        )

    def needing_score(self, now):
        """Ended matches with no result that can still be scored.

        The status and season rules are the same as Match.can_change, which the
        score views check.
        """
        return self.scheduled().filter(
            models.Q(home_score__isnull=True) | models.Q(away_score__isnull=True),
            ends_at__lt=now,
            season__state__in=_live_season_states(),
        )


def lock_facilities(pks):
    """Lock these facilities until the transaction ends, so a venue check holds.

    Bad values (from a posted form) are skipped. The order avoids deadlocks.
    """
    pks = [pk for pk in pks if str(pk).isdecimal() and len(str(pk)) < 19]
    list(
        Facility.objects.select_for_update()
        .filter(pk__in=pks)
        .order_by("pk")
        .values_list("pk")
    )


class Match(models.Model):
    """A game between two teams of one season, at a facility."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CANCELLED = "cancelled", "Cancelled"

    season = models.ForeignKey(
        "teams.Season", on_delete=models.CASCADE, related_name="matches"
    )
    home_team = models.ForeignKey(
        "teams.Team", on_delete=models.PROTECT, related_name="home_matches"
    )
    away_team = models.ForeignKey(
        "teams.Team", on_delete=models.PROTECT, related_name="away_matches"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="matches"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SCHEDULED
    )
    home_score = models.PositiveIntegerField(null=True, blank=True)
    away_score = models.PositiveIntegerField(null=True, blank=True)
    # SET_NULL: deleting a user shouldn't delete or block the match; it just needs
    # a new scorekeeper. Losing the role keeps the link so past matches stay
    # accurate, so anything that acts for a scorekeeper must check the role too.
    scorekeeper = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scorekeeper_matches",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scheduled_matches",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MatchQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "matches"
        ordering = ["starts_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(home_team=models.F("away_team")),
                name="match_teams_differ",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="match_ends_after_start",
            ),
        ]

    def clean(self):
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "The match has to end after it starts."
        if self.home_team_id and self.home_team_id == self.away_team_id:
            errors["away_team"] = "A team can't play itself."
        if self.season_id:
            for field in ("home_team", "away_team"):
                team = getattr(self, field) if getattr(self, f"{field}_id") else None
                if team is not None and team.season_id != self.season_id:
                    errors.setdefault(field, "Choose a team from this season.")
        if (
            self.home_team_id
            and self.away_team_id
            and "home_team" not in errors
            and "away_team" not in errors
            and self.home_team.sport_id != self.away_team.sport_id
        ):
            errors["away_team"] = "Both teams have to play the same sport."
        if (
            self.scorekeeper_id
            and self._scorekeeper_changed()
            and not users_with_role(SCOREKEEPER_ROLE)
            .filter(pk=self.scorekeeper_id)
            .exists()
        ):
            errors["scorekeeper"] = (
                "Only users with the Scorekeeper role can be assigned."
            )
        scored = [self.home_score is not None, self.away_score is not None]
        if any(scored) and not all(scored):
            errors["home_score"] = "Enter both scores, or leave both blank."
            errors["away_score"] = "Enter both scores, or leave both blank."
        if any(scored) and self.status == self.Status.CANCELLED:
            errors["home_score"] = "Cancelled matches can't have a score."
        for field in self._changed_teams_of_scored_match():
            errors.setdefault(
                field,
                "This match has a score, so its teams can't be changed.",
            )
        if errors:
            raise ValidationError(errors)

    def _changed_teams_of_scored_match(self):
        """Team fields that differ from the saved match, when it has a score.

        The score and the player stats belong to the saved teams (#303).
        """
        if self.pk is None:
            return []
        stored = (
            Match.objects.filter(
                pk=self.pk, home_score__isnull=False, away_score__isnull=False
            )
            .values("home_team_id", "away_team_id")
            .first()
        ) or {}
        return [
            field
            for field in ("home_team", "away_team")
            if f"{field}_id" in stored
            and stored[f"{field}_id"] != getattr(self, f"{field}_id")
        ]

    def _scorekeeper_changed(self):
        """A stale scorekeeper can't be newly assigned, but mustn't block other edits."""
        stored = (
            Match.objects.filter(pk=self.pk)
            .values_list("scorekeeper_id", flat=True)
            .first()
        )
        return self.scorekeeper_id != stored

    def validate_schedulable(self):
        """The season must allow scheduling for a match to be created or changed."""
        if self.season_id and not self.season.allows(SeasonAction.SCHEDULE_MATCH):
            raise ValidationError(
                "Matches can only be scheduled while a season is open or active."
            )

    @property
    def can_change(self):
        """Closed seasons are history, so only live seasons' matches can change."""
        return not self.is_cancelled and self.season.allows(SeasonAction.SCHEDULE_MATCH)

    @property
    def has_started(self):
        return self.starts_at <= timezone.now()

    @property
    def can_record_score(self):
        """A League Admin enters a result once the match starts.

        A stored result can always be corrected, also when the match was moved.
        """
        return self.can_change and (self.has_started or self.has_result)

    @property
    def can_submit_score(self):
        """A scorekeeper submits a result once. Later only an admin corrects it."""
        return self.can_record_score and not self.has_result

    def cancel(self):
        self.status = self.Status.CANCELLED
        self.save(update_fields=["status"])

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELLED

    @property
    def has_result(self):
        """Both scores are recorded, so the match counts in the standings."""
        return self.home_score is not None and self.away_score is not None

    @property
    def is_awaiting_score(self):
        """The match has ended with no result, and it isn't cancelled."""
        return (
            not self.is_cancelled
            and not self.has_result
            and self.ends_at < timezone.now()
        )

    def __str__(self):
        return f"{self.home_team} vs {self.away_team}"


class MatchPeriodScore(models.Model):
    """Both teams' points in one period. Periods past Sport.period_count are overtime."""

    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="period_scores"
    )
    period = models.PositiveSmallIntegerField()
    home_points = models.PositiveIntegerField()
    away_points = models.PositiveIntegerField()

    class Meta:
        ordering = ["period"]
        constraints = [
            models.UniqueConstraint(
                fields=["match", "period"], name="unique_period_per_match"
            ),
            models.CheckConstraint(
                condition=models.Q(period__gte=1),
                name="period_score_period_positive",
            ),
        ]

    def clean(self):
        if self.match_id and self.period:
            sport = self.match.home_team.sport
            if self.period > sport.period_count + sport.MAX_OVERTIME_PERIODS:
                raise ValidationError(
                    {"period": "Matches have at most 2 overtime periods."}
                )

    def __str__(self):
        return f"{self.match} period {self.period}"


def validate_match_player(row):
    """A stat or appearance row needs a team in the match and a player on it.

    Roster has no history, so the roster check runs only for a new row or a
    changed player or team. A player who left keeps the rows from before.
    """
    match = row.match
    if row.team_id not in {match.home_team_id, match.away_team_id}:
        raise ValidationError({"team": "Choose a team in this match."})
    stored = None
    if row.pk:
        stored = (
            type(row)
            .objects.filter(pk=row.pk)
            .values_list("player_id", "team_id")
            .first()
        )
    if stored == (row.player_id, row.team_id):
        return
    Roster = apps.get_model("teams", "Roster")
    if not Roster.objects.filter(team_id=row.team_id, player_id=row.player_id).exists():
        raise ValidationError({"player": "That player isn't on this team."})


class PlayerStat(models.Model):
    """A player's count for one event type in one match. Zero isn't stored."""

    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="player_stats"
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="match_stats"
    )
    # The team is stored because leaving a team deletes the Roster row.
    team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="player_stats"
    )
    event_type = models.ForeignKey(
        "teams.EventType", on_delete=models.PROTECT, related_name="player_stats"
    )
    value = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["match", "player", "event_type"],
                name="unique_stat_per_player_event",
            )
        ]

    def clean(self):
        if not (self.match_id and self.player_id and self.team_id):
            return
        validate_match_player(self)
        if (
            self.event_type_id
            and self.event_type.sport_id != self.match.home_team.sport_id
        ):
            raise ValidationError(
                {"event_type": "Choose an event type for this sport."}
            )

    def __str__(self):
        return f"{display_name(self.player)} {self.event_type.name} {self.value} in {self.match}"


class MatchAppearance(models.Model):
    """A player took part in a match, for one team."""

    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="appearances"
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="match_appearances",
    )
    team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="match_appearances"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["match", "player"], name="unique_appearance_per_match"
            )
        ]

    def clean(self):
        if self.match_id and self.player_id and self.team_id:
            validate_match_player(self)

    def __str__(self):
        return f"{display_name(self.player)} played for {self.team} in {self.match}"


class MatchComment(models.Model):
    """One comment on a match page. Comments are flat: no nesting."""

    MAX_BODY_LENGTH = 500

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="match_comments",
    )
    body = models.CharField(max_length=MAX_BODY_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set by a user's report. A League Admin clears it in the moderation queue.
    is_flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{display_name(self.author)} on {self.match}: {self.body[:40]}"
