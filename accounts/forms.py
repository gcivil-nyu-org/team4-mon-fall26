from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    SetPasswordMixin,
    UserCreationForm,
)

from .placeholders import find_user_by_email, is_placeholder, normalize_email

NYU_DOMAIN = "@nyu.edu"
UNVERIFIED_MESSAGE = (
    "Please confirm your email first. Check your inbox for the link, "
    "or request a new one below."
)


class SignUpForm(UserCreationForm):
    """The NYU email doubles as the username, so users log in with their email."""

    email = forms.EmailField(
        label="NYU email", help_text="Usually your NetID, e.g. ab1234@nyu.edu."
    )
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ["email", "first_name", "last_name"]

    def clean_email(self):
        email = normalize_email(self.cleaned_data["email"])

        if not email.endswith(NYU_DOMAIN):
            raise forms.ValidationError("Please use your NYU ID (an @nyu.edu email).")

        existing = find_user_by_email(email)

        # A placeholder (someone added this email to a team) can be claimed.
        # The claim completes only when the email link is opened.
        if existing is not None and is_placeholder(existing):
            self.placeholder = existing
        elif existing is not None:
            raise forms.ValidationError(
                "An account with this email already exists. "
                "Log in, or request a new confirmation email."
            )

        return email

    def save(self, commit=True):
        placeholder = getattr(self, "placeholder", None)
        if placeholder is not None:
            # Don't change the placeholder here: anyone can type this email.
            # The person who opens the email link sets the password and names
            # (ClaimAccountForm), so the account stays with the inbox owner.
            return placeholder
        user = super().save(commit=False)
        user.username = user.email = self.cleaned_data["email"]
        user.is_active = False  # becomes active when the email link is opened

        if commit:
            user.save()

        return user


class ClaimAccountForm(SetPasswordMixin, forms.Form):
    """Shown from the email link for a placeholder: the inbox owner sets the
    names and password, then the account becomes active."""

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    password1, password2 = SetPasswordMixin.create_password_fields()

    def __init__(self, user, *args, **kwargs):
        self.user = user
        kwargs.setdefault(
            "initial", {"first_name": user.first_name, "last_name": user.last_name}
        )
        super().__init__(*args, **kwargs)

    def clean(self):
        self.validate_passwords()
        self.user.first_name = self.cleaned_data.get("first_name", "")
        self.user.last_name = self.cleaned_data.get("last_name", "")
        self.validate_password_for_user(self.user)
        return super().clean()

    def save(self):
        """Set names and password. The caller activates the user."""
        return self.set_password_and_save(self.user, commit=False)


class LoginForm(AuthenticationForm):
    """Log in with the NYU email; tells unverified users why they can't sign in."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].label = "NYU email"

        # Classes come from the template (docs/DESIGN.md, "Forms").
        self.fields["username"].widget.attrs.update(
            {
                "placeholder": "yourname@nyu.edu",
                "autocomplete": "username",
            }
        )

        self.fields["password"].widget.attrs.update(
            {
                "placeholder": "Enter your password",
                "autocomplete": "current-password",
            }
        )

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()

    def clean(self):
        try:
            return super().clean()

        except forms.ValidationError:
            username = self.cleaned_data.get("username") or ""

            user = (
                get_user_model()
                .objects.filter(username__iexact=username, is_active=False)
                .first()
            )

            # Only say "unverified" when the password is right,
            # so the form doesn't reveal who has an account.
            if user and user.check_password(self.cleaned_data.get("password") or ""):
                raise forms.ValidationError(UNVERIFIED_MESSAGE, code="unverified")

            raise


class ResendVerificationForm(forms.Form):
    email = forms.EmailField(label="NYU email")

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()
