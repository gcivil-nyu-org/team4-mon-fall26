from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

NYU_DOMAIN = "@nyu.edu"


class SignUpForm(UserCreationForm):
    """Temporary sign-up until registration with verification (#63, #64) lands.

    The NYU email doubles as the username, so users log in with their email.
    """

    email = forms.EmailField(label="NYU email")
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ["email", "first_name", "last_name"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not email.endswith(NYU_DOMAIN):
            raise forms.ValidationError("Please use your NYU ID (an @nyu.edu email).")
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Log in instead.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user
