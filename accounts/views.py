import logging
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .forms import NYULoginForm, RegistrationForm, ResendConfirmationForm
from .tokens import email_verification_token

logger = logging.getLogger(__name__)

SEND_FAILED = "We could not send the confirmation email. Please try again in a few minutes."


def _console_email_in_use():
    backend = settings.MAILERS.get("default", {}).get("BACKEND", "")
    return backend.endswith("console.EmailBackend")


def send_verification_email(request, user):
    """Email the confirmation link to the NYU address the user typed in."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    link = request.build_absolute_uri(reverse("accounts:verify", args=[uid, token]))
    body = render_to_string("accounts/verification_email.txt", {"link": link})
    send_mail("Confirm your PlayNYU account", body, None, [user.email])
    if _console_email_in_use():
        # The console backend wraps long lines (quoted-printable), which splits the link in the
        # printed email. Log it on one line so it can be copied. Never done with a real email backend.
        logger.warning("DEV ONLY (console email backend). Confirmation link for %s: %s", user.email, link)


class NYULoginView(LoginView):
    authentication_form = NYULoginForm
    template_name = "registration/login.html"


def register(request):
    if request.user.is_authenticated:
        return redirect("teams:list")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            # If the email cannot be sent, the account is rolled back so nothing is left half-made.
            with transaction.atomic():
                user = form.save()
                send_verification_email(request, user)
        except IntegrityError:
            form.add_error("email", "An account with this email already exists.")
        except (SMTPException, OSError):
            form.add_error(None, SEND_FAILED)
        else:
            return redirect("accounts:check_email")
    return render(request, "accounts/register.html", {"form": form})


def check_email(request):
    return render(request, "accounts/check_email.html")


def verify(request, uidb64, token):
    User = get_user_model()
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and email_verification_token.check_token(user, token):
        user.is_active = True
        user.save(update_fields=["is_active"])
        messages.success(request, "Your NYU email is verified. You can log in now.")
        return redirect("login")

    if user is not None and user.is_active:
        # The link was already used (the token dies once the account is active).
        messages.info(request, "This account is already verified. You can log in.")
        return redirect("login")

    return render(request, "accounts/verify_failed.html", status=400)


def resend(request):
    form = ResendConfirmationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = get_user_model().objects.filter(email__iexact=form.cleaned_data["email"], is_active=False).first()
        if user is not None:
            try:
                send_verification_email(request, user)
            except (SMTPException, OSError):
                form.add_error(None, SEND_FAILED)
                return render(request, "accounts/resend.html", {"form": form})
        # Same answer whether or not the address is registered, so this page reveals nothing.
        # TODO(T25): rate-limit this endpoint, like add-player.
        messages.info(
            request,
            "If that NYU address has an account waiting for confirmation, we sent it a new link.",
        )
        return redirect("accounts:check_email")
    return render(request, "accounts/resend.html", {"form": form})
