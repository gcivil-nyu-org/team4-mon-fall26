import re

from django import forms
from django.db import transaction

from .models import PlayerProfile

N_NUMBER_RE = re.compile(r"^N\d{8}$")
NET_ID_RE = re.compile(r"^[a-z]+\d+$")


class ProfileForm(forms.ModelForm):
    """Fields a user may edit on their own profile: first name, last name, N number, NetID.

    Email, verification status and roles are deliberately left out.
    """

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    class Meta:
        model = PlayerProfile
        fields = ["n_number", "net_id"]

    field_order = ["first_name", "last_name", "n_number", "net_id"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["first_name"].initial = user.first_name
        self.fields["last_name"].initial = user.last_name
        self.fields["n_number"].required = True
        self.fields["n_number"].help_text = "N followed by 8 digits, e.g. N12345678."
        self.fields["net_id"].required = True
        self.fields["net_id"].help_text = "Letters then digits, e.g. ab1234."

    def clean_n_number(self):
        value = self.cleaned_data["n_number"].strip().upper()
        if not N_NUMBER_RE.match(value):
            raise forms.ValidationError(
                "Enter your N number as N followed by 8 digits, e.g. N12345678."
            )
        return value

    def clean_net_id(self):
        value = self.cleaned_data["net_id"].strip().lower()
        if not NET_ID_RE.match(value):
            raise forms.ValidationError(
                "Enter your NetID as letters followed by digits, e.g. ab1234."
            )
        return value

    def save(self):
        with transaction.atomic():
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            self.user.save(update_fields=["first_name", "last_name"])
            profile = super().save(commit=False)
            profile.user = self.user
            profile.save()
        return profile
