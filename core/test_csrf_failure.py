"""#271: a stale CSRF token gets a friendly page, not Django's raw 403."""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

EMAIL = "cs1234@nyu.edu"
PASSWORD = "Str0ng-pass-2026"


def csrf_token(response):
    return re.search(
        r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()
    ).group(1)


class CsrfFailureTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.client = Client(enforce_csrf_checks=True)
        self.url = reverse("login")
        self.token = csrf_token(self.client.get(self.url))

    def post_login(self):
        return self.client.post(
            self.url,
            {
                "username": EMAIL,
                "password": PASSWORD,
                "csrfmiddlewaretoken": self.token,
            },
        )

    def test_second_login_submit_goes_home_signed_in(self):
        self.assertRedirects(self.post_login(), reverse("core:home"))
        # The login rotated the token, so this repeat submit fails the check.
        response = self.client.post(
            self.url,
            {
                "username": EMAIL,
                "password": PASSWORD,
                "csrfmiddlewaretoken": self.token,
            },
            follow=True,
        )
        self.assertRedirects(response, reverse("core:home"))
        self.assertContains(response, "You&#x27;re already logged in.")
        self.assertIn("_auth_user_id", self.client.session)

    def test_bad_token_signed_out_shows_friendly_403(self):
        response = self.client.post(
            self.url,
            {"username": EMAIL, "password": PASSWORD, "csrfmiddlewaretoken": "x" * 64},
        )
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "core/csrf_failure.html")
        self.assertContains(response, "This page expired", status_code=403)
        self.assertNotContains(response, "CSRF verification failed", status_code=403)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_bad_token_signed_in_elsewhere_is_still_403(self):
        self.post_login()
        response = self.client.post(
            reverse("accounts:resend"),
            {"email": EMAIL, "csrfmiddlewaretoken": "x" * 64},
        )
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "This page expired", status_code=403)
