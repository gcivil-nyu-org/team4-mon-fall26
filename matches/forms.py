from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils.crypto import salted_hmac

from accounts.roles import SCOREKEEPER_ROLE, users_with_role
from facilities.models import Facility
from teams.models import Team

from .models import Match

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
OVERLAP_CONFIRMATION_FIELD = "overlap_confirmation"


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format=DATETIME_FORMAT, **kwargs)


class MatchForm(forms.ModelForm):
    """League Admins schedule or reschedule a match within one season."""

    class Meta:
        model = Match
        fields = [
            "home_team",
            "away_team",
            "facility",
            "starts_at",
            "ends_at",
            "scorekeeper",
        ]
        labels = {"starts_at": "Starts", "ends_at": "Ends"}
        widgets = {"starts_at": DateTimeLocalInput(), "ends_at": DateTimeLocalInput()}
        help_texts = {"starts_at": "New York time."}

    def __init__(self, *args, season, **kwargs):
        super().__init__(*args, **kwargs)
        self.overlaps = []
        self.overlap_token = ""
        self.instance.season = season
        teams = Team.objects.filter(season=season).select_related("sport")
        for name in ("home_team", "away_team"):
            self.fields[name].queryset = teams
            self.fields[name].label_from_instance = (
                lambda team: f"{team.name} ({team.sport.name})"
            )
        facilities = Facility.objects.filter(is_active=True)
        if self.instance.facility_id:
            # Keep the current facility selectable even if it was deactivated.
            facilities = facilities | Facility.objects.filter(
                pk=self.instance.facility_id
            )
        self.fields["facility"].queryset = facilities.distinct()
        scorekeepers = users_with_role(SCOREKEEPER_ROLE)
        if self.instance.scorekeeper_id:
            # Keep the current scorekeeper selectable even if they lost the role.
            scorekeepers = scorekeepers | get_user_model().objects.filter(
                pk=self.instance.scorekeeper_id
            )
        self.fields["scorekeeper"].queryset = scorekeepers.distinct().order_by(
            "first_name", "last_name", "email"
        )
        self.fields["scorekeeper"].label_from_instance = (
            lambda user: user.get_full_name() or user.email
        )
        self.fields["scorekeeper"].empty_label = "No scorekeeper yet"
        for name in ("starts_at", "ends_at"):
            self.fields[name].input_formats = [DATETIME_FORMAT]

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if self.instance.is_cancelled:
            raise ValidationError("Cancelled matches can't be changed.")
        # Instance fields aren't updated until _post_clean, so read the submitted
        # values from `cleaned` here, not from self.instance.
        try:
            self.instance.validate_schedulable()
        except ValidationError as error:
            self.add_error(None, error)
        facility_changed = self.instance.pk is None or "facility" in self.changed_data
        if facility_changed and not cleaned["facility"].is_active:
            self.add_error("facility", "This facility isn't available.")
        if not self.errors and cleaned["ends_at"] > cleaned["starts_at"]:
            self._find_overlaps(cleaned)
        return cleaned

    def is_valid(self):
        # An overlap is a warning, not an error, but it holds the save back until
        # the admin confirms it.
        return super().is_valid() and not self._overlaps_unconfirmed()

    def _find_overlaps(self, cleaned):
        self.overlaps = list(
            Match.objects.overlapping(
                cleaned["facility"], cleaned["starts_at"], cleaned["ends_at"]
            )
            .exclude(pk=self.instance.pk)
            .select_related("facility", "home_team__sport", "away_team__sport")
        )
        if self.overlaps:
            self.overlap_token = self._overlap_token(cleaned)

    def _overlap_token(self, cleaned):
        """Identifies exactly what the admin was warned about.

        Confirming only counts for the same facility, times and conflicts, so a
        confirmation from an earlier warning can't accept a different conflict.
        """
        warned_about = (
            cleaned["facility"].pk,
            cleaned["starts_at"].timestamp(),
            cleaned["ends_at"].timestamp(),
            [
                (match.pk, match.starts_at.timestamp(), match.ends_at.timestamp())
                for match in self.overlaps
            ],
        )
        return salted_hmac("matches.overlap", repr(warned_about)).hexdigest()

    def _overlaps_unconfirmed(self):
        submitted = self.data.get(OVERLAP_CONFIRMATION_FIELD)
        return bool(self.overlaps) and submitted != self.overlap_token


class ScoreForm(forms.ModelForm):
    """Record or correct a match result. Corrections overwrite the scores."""

    class Meta:
        model = Match
        fields = ["home_score", "away_score"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("home_score", "away_score"):
            self.fields[name].required = True
            self.fields[name].validators.append(MinValueValidator(0))
        match = self.instance
        if match is not None and match.pk:
            self.fields["home_score"].label = f"{match.home_team} score"
            self.fields["away_score"].label = f"{match.away_team} score"

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if self.instance.pk and not self.instance.can_change:
            raise ValidationError(
                "Scores can only be recorded while the season is open or active."
            )
        return cleaned
