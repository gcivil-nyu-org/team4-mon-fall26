from django import forms
from django.core.exceptions import ValidationError

from facilities.models import Facility
from teams.models import Team

from .models import Match

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format=DATETIME_FORMAT, **kwargs)


class MatchForm(forms.ModelForm):
    """League Admins schedule or reschedule a match within one season."""

    class Meta:
        model = Match
        fields = ["home_team", "away_team", "facility", "starts_at", "ends_at"]
        labels = {"starts_at": "Starts", "ends_at": "Ends"}
        widgets = {"starts_at": DateTimeLocalInput(), "ends_at": DateTimeLocalInput()}
        help_texts = {"starts_at": "New York time."}

    def __init__(self, *args, season, **kwargs):
        super().__init__(*args, **kwargs)
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
        return cleaned
