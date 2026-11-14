from django import forms

from accounts.placeholders import find_user_by_email, normalize_email
from accounts.rate_limits import consume_invite_request

from .catalog_rules import name_key, validate_catalog_name
from .models import (
    Division,
    EventType,
    FreeAgentRequest,
    Roster,
    Season,
    Sport,
    Team,
    season_team_for,
)
from .season_rules import SeasonAction, validate_season_dates

NYU_DOMAIN = "@nyu.edu"


class SportForm(forms.ModelForm):
    """Name rules and uniqueness live in Sport.clean (catalog_rules)."""

    class Meta:
        model = Sport
        fields = ["name"]
        labels = {"name": "Sport name"}


class EventTypeForm(forms.ModelForm):
    """Name rules and per-sport uniqueness live in EventType.clean (catalog_rules)."""

    sport = forms.ModelChoiceField(
        queryset=Sport.objects.order_by("name"),
        label="Sport",
        empty_label="Choose a sport",
    )

    class Meta:
        model = EventType
        fields = ["sport", "name"]
        labels = {"name": "Event type name"}


SPORT_HELP = "The season sets the sport. Choose one only when the season has none."


def season_label(season):
    """The season name, with its sport when the name doesn't already say it."""
    if season.sport is None:
        return f"{season.name} (any sport)"
    if season.sport.name.lower() in season.name.lower():
        return season.name
    return f"{season.name} ({season.sport.name})"


class SeasonFieldsMixin:
    """Season, sport and division fields that depend on each other.

    The season comes first. A season with a sport sets the sport, and the
    division must belong to the season. static/js/season_fields.js narrows the
    selects in the browser; these rules hold without it.
    """

    def setup_season_fields(self, seasons):
        seasons = list(
            seasons.select_related("sport")
            .prefetch_related("divisions")
            .order_by("start_date", "name")
        )
        pks = [season.pk for season in seasons]
        self.fields["season"].queryset = (
            Season.objects.filter(pk__in=pks)
            .select_related("sport")
            .order_by("start_date", "name")
        )
        self.fields["season"].label_from_instance = season_label
        division = self.fields["division"]
        division.queryset = Division.objects.filter(season__in=pks)
        # One optgroup for each season, so the list reads well with no JavaScript.
        division.choices = [("", division.empty_label)] + [
            (season_label(season), [(d.pk, d.name) for d in season.divisions.all()])
            for season in seasons
            if season.divisions.all()
        ]
        # Read by static/js/season_fields.js.
        self.season_rules = {
            str(season.pk): {
                "sport": str(season.sport_id) if season.sport_id else "",
                "divisions": [str(d.pk) for d in season.divisions.all()],
            }
            for season in seasons
        }

    def clean_sport(self):
        sport = self.cleaned_data.get("sport")
        if "season" not in self.cleaned_data:
            # The season has its own error. Don't add a second one here.
            return sport
        season = self.cleaned_data["season"]
        if season is not None and season.sport_id:
            # A disabled select sends nothing, and a stale choice must not win.
            return season.sport
        if sport is None:
            raise forms.ValidationError(
                self.fields["sport"].error_messages["required"], code="required"
            )
        return sport

    def clean_division(self):
        division = self.cleaned_data.get("division")
        season = self.cleaned_data.get("season")
        if division and (season is None or division.season_id != season.pk):
            raise forms.ValidationError("Choose a division from the selected season.")
        return division


class TeamCreateForm(SeasonFieldsMixin, forms.ModelForm):
    sport = forms.ModelChoiceField(
        queryset=Sport.objects.all().order_by("name"),
        label="Sport",
        required=False,
        empty_label="Choose a sport",
        help_text=SPORT_HELP,
    )

    class Meta:
        model = Team
        fields = ["name", "season", "sport", "division"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["season"].empty_label = "No season"
        self.fields["division"].required = False
        self.fields["division"].empty_label = "No division"
        self.setup_season_fields(Season.objects.allowing(SeasonAction.CREATE_TEAM))

    def clean_season(self):
        season = self.cleaned_data["season"]
        current = season_team_for(self.user, season)
        if current is not None:
            raise forms.ValidationError(
                f"You're already on {current.name} this season. "
                "Players can be on one team per season."
            )
        return season


class DivisionCreateForm(forms.ModelForm):
    class Meta:
        model = Division
        fields = ["name"]

    def __init__(self, *args, season, **kwargs):
        super().__init__(*args, **kwargs)
        self.season = season
        self.instance.season = season

    def clean_name(self):
        name = validate_catalog_name(self.cleaned_data["name"])
        key = name_key(name)
        existing = Division.objects.filter(season=self.season, name_key=key)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError(
                "A division with this name already exists in this season."
            )
        return name

    def save(self, commit=True):
        division = super().save(commit=False)
        division.season = self.season
        if commit:
            division.save()
        return division


class AddPlayerForm(forms.Form):
    """Any @nyu.edu email can be added, with or without an account.

    When no user has the email, `player` is None and the view creates a
    placeholder account (accounts/placeholders.py). The errors never say
    whether an account exists.

    Every add with an @nyu.edu email counts toward the inviter's rate limit,
    before the account lookup. So the limit error doesn't say whether an
    account exists either.
    """

    email = forms.EmailField(
        label="Player's NYU email",
        help_text="They don't need an account yet. We'll email them to sign up.",
    )

    def __init__(self, *args, team, inviter, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.inviter = inviter
        self.player = None

    def clean_email(self):
        email = normalize_email(self.cleaned_data["email"])
        if not email.endswith(NYU_DOMAIN):
            raise forms.ValidationError("Only @nyu.edu emails can be added.")
        # New placeholders get an invite email, so limit adds per inviter.
        if not consume_invite_request(self.inviter).allowed:
            raise forms.ValidationError(
                "You've added a lot of players today. Try again tomorrow."
            )

        # Active or not: unverified sign-ups and placeholders can be added too.
        user = find_user_by_email(email)
        # A new placeholder can't be on any team yet, so only the size check applies.
        if user and Roster.objects.filter(team=self.team, player=user).exists():
            raise forms.ValidationError("That player is already on this team.")
        if self.team.is_full():
            raise forms.ValidationError(
                f"The roster is full ({self.team.max_roster_size} players)."
            )
        if user is None:
            return email
        current = season_team_for(user, self.team.season)
        if current is not None:
            # Don't name the other team: the captain may not be allowed to see it.
            raise forms.ValidationError(
                "That player is already on another team this season."
            )

        self.player = user
        return email


class FreeAgentRequestForm(SeasonFieldsMixin, forms.Form):
    season = forms.ModelChoiceField(
        queryset=Season.objects.none(),
        label="Season",
        empty_label="Choose a season",
    )
    sport = forms.ModelChoiceField(
        queryset=Sport.objects.all().order_by("name"),
        label="Sport",
        required=False,
        empty_label="Choose a sport",
        help_text=SPORT_HELP,
    )

    division = forms.ModelChoiceField(
        queryset=Division.objects.none(),
        label="Division",
        required=False,
        empty_label="No division",
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.setup_season_fields(
            Season.objects.allowing(SeasonAction.REQUEST_FREE_AGENT)
            .exclude(teams__roster__player=user)
            .distinct()
        )

    def clean_season(self):
        season = self.cleaned_data["season"]
        if season_team_for(self.user, season) is not None:
            raise forms.ValidationError(
                "You already have a team in this season and can't request placement."
            )
        if FreeAgentRequest.objects.filter(player=self.user, season=season).exists():
            raise forms.ValidationError("You already requested placement this season.")
        return season


class SeasonForm(forms.ModelForm):
    """League Admins create and edit seasons. State changes go through the state buttons."""

    sport = forms.ModelChoiceField(
        queryset=Sport.objects.order_by("name"),
        label="Sport",
        required=False,
        empty_label="Any sport",
        help_text="Teams in this season must play this sport. Leave blank for any.",
    )
    # A select, not a checkbox: a POST without the field keeps the current value.
    auto_state = forms.TypedChoiceField(
        label="Automatic state changes",
        choices=[
            ("on", "On: change state by date"),
            ("off", "Off: only a League Admin changes the state"),
        ],
        coerce=lambda value: value == "on",
        empty_value=None,
        required=False,
        help_text=(
            "When on, the season becomes active on the day after registration "
            "closes, and closed on the day after the end date. Draft seasons "
            "never change."
        ),
    )

    class Meta:
        model = Season
        fields = [
            "name",
            "sport",
            "start_date",
            "registration_closes_on",
            "end_date",
            "max_roster_size",
            "auto_state",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "registration_closes_on": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {"registration_closes_on": "Registration closes on"}
        help_texts = {
            "end_date": "Optional. Can be the same day as the start.",
            "registration_closes_on": (
                "Optional. Teams can register until this date. "
                "On the next day the season becomes active."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["auto_state"] = "on" if self.instance.auto_state else "off"

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean_auto_state(self):
        value = self.cleaned_data.get("auto_state")
        return self.instance.auto_state if value is None else value

    def clean_sport(self):
        sport = self.cleaned_data.get("sport")
        if sport and self.instance.pk:
            others = self.instance.teams.exclude(sport=sport)
            if others.exists():
                raise forms.ValidationError(
                    "This season has teams of another sport. Move or remove "
                    f"them before you set the sport to {sport.name}."
                )
        return sport

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start:
            try:
                validate_season_dates(start, end)
            except forms.ValidationError as error:
                self.add_error(None, error)
        return cleaned
