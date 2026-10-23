from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from profiles.forms import NET_ID_RE
from profiles.models import PlayerProfile

from .emails import send_verification_email
from .forms import LoginForm, ResendVerificationForm, SignUpForm
from .tokens import email_verification_token


def signup(request):
    if request.user.is_authenticated:
        return redirect("teams:list")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        send_verification_email(request, user)
        request.session["verification_email"] = user.email
        return redirect("accounts:check_email")
    return render(request, "accounts/signup.html", {"form": form})


def check_email(request):
    """Screen 1: tell the user a confirmation link is on its way."""
    return render(request, "accounts/check_email.html", {"email": request.session.get("verification_email")})


def verify(request, uidb64, token):
    """Screen 2 when the link is good, screen 3 when it is expired, used or broken."""
    try:
        user = get_user_model().objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (ValueError, OverflowError, get_user_model().DoesNotExist):
        user = None

    if user is None or user.is_active or not email_verification_token.check_token(user, token):
        return render(request, "accounts/link_invalid.html", {"form": ResendVerificationForm()}, status=400)

    with transaction.atomic():
        user.is_active = True
        user.save(update_fields=["is_active"])
        PlayerProfile.objects.get_or_create(user=user, defaults={"net_id": _net_id_from_email(user.email)})
        # TODO(#59): add the Casual Player role once role membership exists.
    return render(request, "accounts/verified.html", {"user": user})


def _net_id_from_email(email):
    """NYU emails are usually netid@nyu.edu; use that as the starting NetID when it fits."""
    local = email.split("@")[0].lower()
    if NET_ID_RE.match(local) and not PlayerProfile.objects.filter(net_id=local).exists():
        return local
    return None


def resend_verification(request):
    form = ResendVerificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        user = get_user_model().objects.filter(email__iexact=email, is_active=False).first()
        if user:
            send_verification_email(request, user)
        # Same screen either way, so this form doesn't reveal which emails have accounts.
        request.session["verification_email"] = email
        return redirect("accounts:check_email")
    return render(request, "accounts/link_invalid.html", {"form": form, "resend_only": True})


class PlayNYULoginView(LoginView):
    authentication_form = LoginForm
