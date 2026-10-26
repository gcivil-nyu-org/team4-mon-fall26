from django import forms
from django.contrib.auth import get_user_model

from .models import Roster, Team, season_team_for

NYU_DOMAIN = "@nyu.edu"


class TeamCreateForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "sport", "season"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_season(self):
        season = self.cleaned_data["season"]
        current = season_team_for(self.user, season)
        if current is not None:
            raise forms.ValidationError(
                f"You're already on {current.name} this season. "
                "Players can be on one team per season."
            )
        return season


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
