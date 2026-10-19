from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q

NYU_DOMAIN = "@nyu.edu"
NON_NYU_MESSAGE = "Please use your NYU ID"


def normalize_email(value):
    return (value or "").strip().lower()


class RegistrationForm(forms.Form):
    """Sign-up with an NYU email. The account stays inactive until the email is confirmed."""

    email = forms.EmailField(
        label="NYU email",
        max_length=150,  # the email is also the username, which allows 150 characters
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_email(self):
        email = normalize_email(self.cleaned_data["email"])
        # endswith("@nyu.edu") rejects look-alikes such as a@nyu.edu.evil.com and a@notnyu.edu.
        if not email.endswith(NYU_DOMAIN):
            raise ValidationError(NON_NYU_MESSAGE)

        User = get_user_model()
        if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise ValidationError(
                "An account with this email already exists. Log in, or request a new confirmation email."
            )
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                email = cleaned.get("email", "")
                candidate = get_user_model()(username=email, email=email)
                try:
                    validate_password(password1, candidate)
                except ValidationError as error:
                    self.add_error("password1", error)
        return cleaned

    def save(self):
        email = self.cleaned_data["email"]
        # The email doubles as the username, and the user cannot log in until verified.
        return get_user_model().objects.create_user(
            username=email,
            email=email,
            password=self.cleaned_data["password1"],
            is_active=False,
        )


class ResendConfirmationForm(forms.Form):
    email = forms.EmailField(label="NYU email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))

    def clean_email(self):
        return normalize_email(self.cleaned_data["email"])


def resolve_username(identifier):
    """Let people log in with their email as well as a plain username (admin, demo users)."""
    identifier = (identifier or "").strip()
    User = get_user_model()
    if User.objects.filter(username=identifier).exists():
        return identifier
    by_email = User.objects.filter(email__iexact=identifier).order_by("pk").first()
    if by_email is not None:
        return by_email.get_username()
    return identifier.lower()


class NYULoginForm(AuthenticationForm):
    username = forms.CharField(
        label="NYU email",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "unverified": (
            "Your account is not verified yet. Click the confirmation link we emailed to your "
            "NYU address, or request a new one."
        ),
    }

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username and password:
            self.cleaned_data["username"] = resolve_username(username)
            try:
                return super().clean()
            except ValidationError as error:
                # Only someone who knows the right password learns the account is unverified,
                # so this cannot be used to find out which emails are registered.
                if error.code == "invalid_login" and self._is_unverified(password):
                    raise ValidationError(self.error_messages["unverified"], code="unverified")
                raise
        return super().clean()

    def _is_unverified(self, password):
        user = get_user_model().objects.filter(username=self.cleaned_data["username"]).first()
        return bool(user and not user.is_active and user.check_password(password))
