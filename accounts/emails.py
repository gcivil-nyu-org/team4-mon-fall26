from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token


def send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    link = request.build_absolute_uri(reverse("accounts:verify", args=[uid, token]))
    body = render_to_string(
        "accounts/verification_email.txt", {"user": user, "link": link}
    )
    send_mail("Confirm your PlayNYU account", body, None, [user.email])
