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
from .roles import CASUAL_PLAYER_ROLE, assign_role
from .rate_limits import (
    clear_login_failures,
    consume_verification_email_request,
    login_rate_limit_status,
    record_login_failure,
)
from .tokens import email_verification_token


def signup(request):
    if request.user.is_authenticated:
        return redirect("teams:list")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        decision = consume_verification_email_request(
            form.cleaned_data["email"], request
        )
        if not decision.allowed:
            form.add_error(
                None,
                "Too many confirmation requests. Please wait before trying again.",
            )
            response = render(request, "accounts/signup.html", {"form": form})
            response.status_code = 429
            response["Retry-After"] = str(decision.retry_after)
            return response

        user = form.save()
        send_verification_email(request, user)
        request.session["verification_email"] = user.email
        request.session["verification_rate_limited"] = False
        return redirect("accounts:check_email")
    return render(request, "accounts/signup.html", {"form": form})


def check_email(request):
    """Show the confirmation and resend flow without disclosing account status."""
    return render(
        request,
        "accounts/check_email.html",
        {
            "email": request.session.get("verification_email"),
            "rate_limited": request.session.pop("verification_rate_limited", False),
        },
    )


def verify(request, uidb64, token):
    """Screen 2 when the link is good, screen 3 when it is expired, used or broken."""
    try:
        user = get_user_model().objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (ValueError, OverflowError, get_user_model().DoesNotExist):
        user = None

    if (
        user is None
        or user.is_active
        or not email_verification_token.check_token(user, token)
    ):
        return render(
            request,
            "accounts/link_invalid.html",
            {"form": ResendVerificationForm()},
            status=400,
        )

    with transaction.atomic():
        user.is_active = True
        user.save(update_fields=["is_active"])
        PlayerProfile.objects.get_or_create(
            user=user, defaults={"net_id": _net_id_from_email(user.email)}
        )
        assign_role(user, CASUAL_PLAYER_ROLE)
    return render(request, "accounts/verified.html", {"verified_user": user})


def _net_id_from_email(email):
    """NYU emails are usually netid@nyu.edu; use that as the starting NetID when it fits."""
    local = email.split("@")[0].lower()
    if (
        NET_ID_RE.match(local)
        and not PlayerProfile.objects.filter(net_id=local).exists()
    ):
        return local
    return None


def resend_verification(request):
    form = ResendVerificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        decision = consume_verification_email_request(email, request)
        user = (
            get_user_model()
            .objects.filter(email__iexact=email, is_active=False)
            .first()
        )
        if user and decision.allowed:
            send_verification_email(request, user)
        # Same screen either way, so this form doesn't reveal which emails have accounts.
        request.session["verification_email"] = email
        request.session["verification_rate_limited"] = not decision.allowed
        return redirect("accounts:check_email")
    return render(
        request, "accounts/link_invalid.html", {"form": form, "resend_only": True}
    )


class PlayNYULoginView(LoginView):
    authentication_form = LoginForm

    def post(self, request, *args, **kwargs):
        email = request.POST.get("username", "").strip().lower()
        decision = login_rate_limit_status(email, request)
        if not decision.allowed:
            # Use an unbound form so rendering this response won't run password
            # verification again for a request that has already been throttled.
            form = self.get_form_class()(request=request, initial={"username": email})
            response = self.render_to_response(
                self.get_context_data(form=form, rate_limited=True)
            )
            response.status_code = 429
            response["Retry-After"] = str(decision.retry_after)
            return response
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        email = self.request.POST.get("username", "").strip().lower()
        record_login_failure(email, self.request)
        if any(
            error.code == "unverified" for error in form.non_field_errors().as_data()
        ):
            # Keep the distinction private until the password is correct, then
            # send the user to the existing confirmation/resend flow.
            self.request.session["verification_email"] = email
            self.request.session["verification_rate_limited"] = False
            return redirect("accounts:check_email")
        return super().form_invalid(form)

    def form_valid(self, form):
        email = form.cleaned_data.get("username", "").strip().lower()
        clear_login_failures(email, self.request)
        return super().form_valid(form)
