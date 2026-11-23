from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from profiles.forms import NET_ID_RE
from profiles.models import PlayerProfile
from profiles.net_ids import release_net_id

from .emails import send_verification_email
from .forms import ClaimAccountForm, LoginForm, ResendVerificationForm, SignUpForm
from .models import PendingAccount
from .placeholders import awaits_verification, is_placeholder
from .roles import CASUAL_PLAYER_ROLE, assign_role
from .rate_limits import (
    clear_login_failures,
    consume_verification_email_request,
    login_rate_limit_status,
    record_login_failure,
)
from .tokens import email_verification_token

# Session key: the account this browser made and chose the password for.
SIGNED_UP_USER = "signed_up_user"


def signup(request):
    if request.user.is_authenticated:
        return redirect("core:home")
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
        if form.created:
            request.session[SIGNED_UP_USER] = user.pk
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


def _link_user(uidb64, token, *, lock=False):
    """The inactive user this link is for, or None when the link is not good."""
    users = get_user_model().objects.all()
    if lock:
        users = users.select_for_update()
    try:
        user = users.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (ValueError, OverflowError, get_user_model().DoesNotExist):
        return None
    if not awaits_verification(user):
        return None
    if not email_verification_token.check_token(user, token):
        return None
    user.is_placeholder = is_placeholder(user)
    return user


def _link_invalid(request):
    return render(
        request,
        "accounts/link_invalid.html",
        {"form": ResendVerificationForm()},
        status=400,
    )


def _claim_page(request, form):
    return render(
        request,
        "accounts/claim.html",
        {"form": form, "is_placeholder": form.user.is_placeholder},
    )


def _activate(user):
    """Call inside a transaction. Activation also makes the link stop working."""
    user.is_active = True
    user.save()
    # The placeholder is now claimed.
    PendingAccount.objects.filter(user=user).delete()
    net_id = _net_id_from_email(user.email)
    if net_id:
        # The verified email proves whose NetID this is (#304).
        release_net_id(net_id, user)
    PlayerProfile.objects.get_or_create(user=user, defaults={"net_id": net_id})
    assign_role(user, CASUAL_PLAYER_ROLE)


def verify(request, uidb64, token):
    """Screen 2 when the link is good, screen 3 when it is expired, used or broken.

    Anyone can type an email on the sign-up form, so the link proves the inbox
    but not who chose the password (#302). It activates at once only in the
    browser that signed up. Otherwise, and for a placeholder, it opens a claim
    page: the account becomes active when the inbox owner sets a password there.
    """
    user = _link_user(uidb64, token)
    if user is None:
        return _link_invalid(request)

    if not user.is_placeholder and request.session.get(SIGNED_UP_USER) == user.pk:
        with transaction.atomic():
            _activate(user)
        del request.session[SIGNED_UP_USER]
        return render(request, "accounts/verified.html", {"verified_user": user})

    if request.method != "POST":
        form = ClaimAccountForm(user)
        return _claim_page(request, form)

    with transaction.atomic():
        # Lock and check the token again, so two posts can't both claim.
        user = _link_user(uidb64, token, lock=True)
        if user is None:
            return _link_invalid(request)
        form = ClaimAccountForm(user, request.POST)
        if not form.is_valid():
            return _claim_page(request, form)
        form.save()
        _activate(user)
    # The inbox owner just chose this password here, so sign them in (#270).
    login(request, user)
    messages.success(request, "Your account is active. Welcome to PlayNYU.")
    return redirect("core:home")


def _net_id_from_email(email):
    """NYU emails are usually netid@nyu.edu; use that as the starting NetID when it fits."""
    local = email.split("@")[0].lower()
    return local if NET_ID_RE.match(local) else None


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
        sendable = user and awaits_verification(user)
        if sendable and decision.allowed:
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
    redirect_authenticated_user = True

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
