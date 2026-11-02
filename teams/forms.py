from django import forms
from django.contrib.auth import get_user_model

from .catalog_rules import name_key, validate_catalog_name
from .models import Division, FreeAgentRequest, Roster, Season, Team, season_team_for

NYU_DOMAIN = "@nyu.edu"


class TeamCreateForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "sport", "season", "division"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["division"].required = False
        self.fields["division"].empty_label = "No division"
        self.fields["division"].queryset = Division.objects.select_related(
            "season"
        ).order_by("season__name", "name")
        self.fields["division"].label_from_instance = (
            lambda division: f"{division.name} — {division.season.name}"
        )

    def clean_season(self):
        season = self.cleaned_data["season"]
        current = season_team_for(self.user, season)
        if current is not None:
            raise forms.ValidationError(
                f"You're already on {current.name} this season. "
                "Players can be on one team per season."
            )
        return season

    def clean_division(self):
        division = self.cleaned_data.get("division")
        season = self.cleaned_data.get("season")
        if division and (season is None or division.season_id != season.pk):
            raise forms.ValidationError("Choose a division from the selected season.")
        return division


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
    email = forms.EmailField(label="Player's NYU email")

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not email.endswith(NYU_DOMAIN):
            raise forms.ValidationError("Only @nyu.edu emails can be added.")

        # Unverified accounts are inactive, so this only finds verified players.
        # TODO(T25): this error reveals whether an account exists; rate-limit this endpoint.
        user = (
            get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        )
        if user is None:
            raise forms.ValidationError("No PlayNYU account with that email.")
        if Roster.objects.filter(team=self.team, player=user).exists():
            raise forms.ValidationError("That player is already on this team.")
        if self.team.is_full():
            raise forms.ValidationError(
                f"The roster is full ({self.team.max_roster_size} players)."
            )
        current = season_team_for(user, self.team.season)
        if current is not None:
            # Don't name the other team: the captain may not be allowed to see it.
            raise forms.ValidationError(
                "That player is already on another team this season."
            )

        self.player = user
        return email


class FreeAgentRequestForm(forms.Form):
    season = forms.ModelChoiceField(
        queryset=Season.objects.none(),
        label="Season",
        empty_label="Choose a season",
    )
    sport = forms.CharField(max_length=50, label="Sport")
    division = forms.ModelChoiceField(
        queryset=Division.objects.none(),
        label="Division",
        required=False,
        empty_label="No division",
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["division"].queryset = Division.objects.select_related(
            "season"
        ).order_by("season__name", "name")
        self.fields["division"].label_from_instance = (
            lambda division: f"{division.name} — {division.season.name}"
        )
        self.fields["season"].queryset = (
            Season.objects.filter(is_active=True)
            .exclude(teams__roster__player=user)
            .order_by("start_date", "name")
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

    def clean_sport(self):
        return self.cleaned_data["sport"].strip()

    def clean_division(self):
        division = self.cleaned_data.get("division")
        season = self.cleaned_data.get("season")
        if division and (season is None or division.season_id != season.pk):
            raise forms.ValidationError("Choose a division from the selected season.")
        return division
