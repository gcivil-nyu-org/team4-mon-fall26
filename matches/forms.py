from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.utils.html import format_html

from accounts.roles import SCOREKEEPER_ROLE, users_with_role
from core.names import display_name
from facilities.models import Facility
from teams.models import Division, Roster, Season, Sport, Team
from teams.season_rules import SeasonState

from .models import Match, MatchComment
from .schedule import SCHEDULE_SORTS, SCHEDULE_TABS

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
        self.fields["scorekeeper"].label_from_instance = display_name
        self.fields["scorekeeper"].empty_label = "No scorekeeper yet"
        # form_fields.html renders help text with |safe, so build it with format_html.
        roles_url = reverse("accounts:roles")
        # Count role holders only: a kept former scorekeeper doesn't count.
        if users_with_role(SCOREKEEPER_ROLE).exists():
            hint = 'Only Scorekeepers are listed. <a href="{}">Manage roles</a>'
        else:
            hint = (
                'No one has the Scorekeeper role yet. <a href="{}">Grant the role</a>'
            )
        self.fields["scorekeeper"].help_text = format_html(hint, roles_url)
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

    def __init__(self, *args, required=True, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("home_score", "away_score"):
            self.fields[name].required = required
            self.fields[name].validators.append(MinValueValidator(0))
            self.fields[name].validators.append(MaxValueValidator(9999))
        if not required:
            # The match sheet: entered periods replace these two values.
            self.fields["away_score"].help_text = (
                "When you enter periods, the final score is their total."
            )
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


class ScheduleFilterForm(forms.Form):
    """GET filters for the schedule table.

    Every field is optional. A value that doesn't clean (a stale bookmark, a
    hidden season) is dropped, and the other filters still apply, like
    teams.forms.FreeAgentFilterForm. Seasons come from seasons_visible_to(),
    so players never see a draft season here.
    """

    sport = forms.ModelChoiceField(
        queryset=Sport.objects.order_by("name"),
        required=False,
        empty_label="All sports",
    )
    season = forms.ModelChoiceField(
        queryset=Season.objects.none(), required=False, empty_label="All seasons"
    )
    team = forms.ModelChoiceField(
        queryset=Team.objects.none(), required=False, empty_label="All teams"
    )
    venue = forms.ModelChoiceField(
        queryset=Facility.objects.none(), required=False, empty_label="All venues"
    )
    division = forms.ModelChoiceField(
        queryset=Division.objects.none(), required=False, empty_label="All divisions"
    )
    mine = forms.ChoiceField(choices=[("1", "My teams")], required=False)
    tab = forms.ChoiceField(
        choices=[(tab, tab) for tab in SCHEDULE_TABS], required=False
    )
    sort = forms.ChoiceField(
        choices=[(sort, sort) for sort in SCHEDULE_SORTS], required=False
    )

    FILTERS = ("sport", "season", "team", "venue", "division", "mine")

    def __init__(self, *args, seasons, **kwargs):
        kwargs.setdefault("auto_id", "filter_%s")
        super().__init__(*args, **kwargs)
        self.fields["season"].queryset = seasons.order_by("-start_date", "name")
        self.fields["season"].label_from_instance = _season_option
        teams = Team.objects.filter(season__in=seasons).select_related("season")
        self.fields["team"].queryset = teams
        # One optgroup for each season, so teams with the same name stay apart.
        groups = {}
        for team in teams.order_by("-season__start_date", "season__name", "name"):
            groups.setdefault(team.season.name, []).append((team.pk, team.name))
        self.fields["team"].choices = [("", "All teams")] + list(groups.items())
        self.fields["venue"].queryset = (
            Facility.objects.filter(matches__season__in=seasons)
            .distinct()
            .order_by("name")
        )
        self.fields["division"].queryset = Division.objects.filter(
            season__in=seasons
        ).order_by("name", "pk")

    def clean(self):
        cleaned = super().clean()
        season, division = cleaned.get("season"), cleaned.get("division")
        if division and (season is None or division.season_id != season.pk):
            # A division only narrows its own season's matches.
            del cleaned["division"]
        return cleaned

    def values(self):
        """The cleaned values that apply, by field name. Bad ones are left out."""
        # An unbound form has no cleaned_data, and fields with errors are missing.
        self.is_valid()
        cleaned = getattr(self, "cleaned_data", {})
        return {name: value for name, value in cleaned.items() if value}

    def filter(self, matches, user):
        values = self.values()
        if "sport" in values:
            matches = matches.filter(home_team__sport=values["sport"])
        if "season" in values:
            matches = matches.filter(season=values["season"])
        if "team" in values:
            team = values["team"]
            matches = matches.filter(Q(home_team=team) | Q(away_team=team))
        if "venue" in values:
            matches = matches.filter(facility=values["venue"])
        if "division" in values:
            # Matches have no division of their own, so it comes from their teams.
            division = values["division"]
            matches = matches.filter(
                Q(home_team__division=division) | Q(away_team__division=division)
            )
        if "mine" in values:
            team_ids = Roster.objects.filter(player=user).values("team_id")
            matches = matches.filter(
                Q(home_team__in=team_ids) | Q(away_team__in=team_ids)
            )
        return matches


def _season_option(season):
    """Admins see draft seasons, marked so they know players can't."""
    if season.state == SeasonState.DRAFT:
        return f"{season.name} (draft)"
    return season.name


class MatchCommentForm(forms.ModelForm):
    class Meta:
        model = MatchComment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": MatchComment.MAX_BODY_LENGTH,
                    "placeholder": "Comment on this match…",
                }
            ),
        }
        labels = {"body": "Your comment"}
        help_texts = {"body": f"Up to {MatchComment.MAX_BODY_LENGTH} characters."}

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise ValidationError("Write a comment before posting.")
        return body
