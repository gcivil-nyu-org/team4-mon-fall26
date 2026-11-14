"""Placeholder accounts for players who are added before they sign up.

A placeholder is an inactive user with an unusable password and a
PendingAccount row. Signing up with the same email claims it: the person
keeps the same user, with its teams and match history.

placeholder_for needs no request, so management commands can call it.
"""

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse

from .models import PendingAccount


def normalize_email(email):
    return (email or "").strip().lower()


def placeholder_for(email, *, first_name="", last_name="", invited_by=None):
    """Return (user, created) for this email.

    An existing user with this email or username comes back unchanged, with
    created False. Otherwise this creates an inactive user with an unusable
    password, plus its PendingAccount row.
    """
    email = normalize_email(email)
    User = get_user_model()
    existing = User.objects.filter(
        Q(email__iexact=email) | Q(username__iexact=email)
    ).first()
    if existing is not None:
        return existing, False

    with transaction.atomic():
        user = User(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_active=False,
        )
        user.set_unusable_password()
        user.save()
        PendingAccount.objects.create(user=user, invited_by=invited_by)
    return user, True


def is_placeholder(user):
    return PendingAccount.objects.filter(user=user).exists()


def send_invite_email(request_or_base_url, user, team, invited_by):
    """Tell a new placeholder that they are on a team and can sign up.

    The first argument is a request, or a base URL such as
    "https://playnyu.example.com" when there is no request.
    """
    path = reverse("accounts:signup")
    if isinstance(request_or_base_url, str):
        link = request_or_base_url.rstrip("/") + path
    else:
        link = request_or_base_url.build_absolute_uri(path)
    inviter = None
    if invited_by is not None:
        inviter = invited_by.get_full_name() or invited_by.email
    body = render_to_string(
        "accounts/invite_email.txt",
        {"user": user, "team": team, "inviter": inviter, "link": link},
    )
    send_mail(f"You were added to {team.name} on PlayNYU", body, None, [user.email])
