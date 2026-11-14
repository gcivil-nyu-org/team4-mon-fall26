"""Placeholder accounts for players who are added before they sign up.

A placeholder is an inactive user with an unusable password and a
PendingAccount row. Signing up with the same email sends a link. The person
who opens the link claims the placeholder on the claim page: they set the
names and password and keep the same user, with its teams and match history.

placeholder_for needs no request, so management commands can call it.
"""

import logging

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse

from .models import PendingAccount

logger = logging.getLogger(__name__)


def normalize_email(email):
    return (email or "").strip().lower()


def find_user_by_email(email):
    """Return the user whose email or username matches `email`, or None.

    The match ignores case and surrounding spaces. Inactive users match too.
    """
    email = normalize_email(email)
    return (
        get_user_model()
        .objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
        .first()
    )


def placeholder_for(email, *, first_name="", last_name="", invited_by=None):
    """Return (user, created) for this email.

    An existing user with this email or username comes back unchanged, with
    created False. Otherwise this creates an inactive user with an unusable
    password, plus its PendingAccount row.
    """
    email = normalize_email(email)
    existing = find_user_by_email(email)
    if existing is not None:
        return existing, False

    try:
        # The savepoint keeps a lost race from breaking the caller's transaction.
        with transaction.atomic():
            user = get_user_model()(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_active=False,
            )
            user.set_unusable_password()
            user.save()
            PendingAccount.objects.create(user=user, invited_by=invited_by)
    except IntegrityError:
        # Another request made this user after the check above.
        existing = find_user_by_email(email)
        if existing is None:
            raise
        return existing, False
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
    # A newline in the subject would make send_mail raise BadHeaderError.
    team_name = " ".join(team.name.splitlines())
    send_mail(f"You were added to {team_name} on PlayNYU", body, None, [user.email])


def send_invite_email_safely(request_or_base_url, user, team, invited_by):
    """Send the invite email. Log a failure instead of raising it.

    The view calls this after the roster row commits, so a mail error must
    not turn a successful add into a 500.
    """
    try:
        send_invite_email(request_or_base_url, user, team, invited_by)
    except Exception:
        # Log the user id, not the email address.
        logger.exception("Invite email failed for user %s", user.pk)
        return False
    return True
