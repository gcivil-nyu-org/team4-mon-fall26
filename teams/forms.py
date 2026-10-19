from django import forms
from django.contrib.auth import get_user_model

from .models import Roster, Team

NYU_DOMAIN = "@nyu.edu"


class TeamCreateForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "sport", "season"]


class AddPlayerForm(forms.Form):
    email = forms.EmailField(label="Player's NYU email")

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not email.endswith(NYU_DOMAIN):
            raise forms.ValidationError("Only @nyu.edu emails can be added.")

        # TODO(T8): once verification lands, only allow verified players.
        # TODO(T25): this error reveals whether an account exists; rate-limit this endpoint.
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            raise forms.ValidationError("No PlayNYU account with that email.")
        if Roster.objects.filter(team=self.team, player=user).exists():
            raise forms.ValidationError("That player is already on this team.")

        self.player = user
        return email
