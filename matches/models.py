from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from teams.season_rules import SeasonAction


class MatchQuerySet(models.QuerySet):
    def scheduled(self):
        return self.filter(status=Match.Status.SCHEDULED)

    def overlapping(self, facility, starts_at, ends_at):
        """Scheduled matches at a facility that share time with a window.

        A match ending exactly when the window starts, or starting exactly when
        it ends, doesn't overlap it.
        """
        return self.scheduled().filter(
            facility=facility, starts_at__lt=ends_at, ends_at__gt=starts_at
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
        if errors:
            raise ValidationError(errors)

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

    def cancel(self):
        self.status = self.Status.CANCELLED
        self.save(update_fields=["status"])

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELLED

    def __str__(self):
        return f"{self.home_team} vs {self.away_team}"
