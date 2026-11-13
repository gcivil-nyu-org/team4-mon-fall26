"""Verification gate (#168): unverified users can't reach league pages.

Signing up leaves is_active=False until the email link is opened, and
Django's auth backend refuses inactive users — so an unverified user can
never hold a session. The login form turns a correct password into a
redirect to the check-email page instead of a session. These tests pin
that behavior, which is why no extra redirect middleware is needed.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class UnverifiedUserTests(TestCase):
    def setUp(self):
        self.email = "newstudent@nyu.edu"
        self.password = "testpass123"
        self.unverified = get_user_model().objects.create_user(
            username=self.email,
            email=self.email,
            password=self.password,
            is_active=False,
        )

    def test_unverified_login_redirects_to_check_email(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.email, "password": self.password},
        )
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unverified_user_cannot_open_a_league_page(self):
        self.client.post(
            reverse("login"),
            {"username": self.email, "password": self.password},
        )
        response = self.client.get(reverse("teams:league_setup"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_verified_user_logs_in_and_reaches_pages(self):
        self.unverified.is_active = True
        self.unverified.save(update_fields=["is_active"])
        response = self.client.post(
            reverse("login"),
            {"username": self.email, "password": self.password},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("teams:list")).status_code, 200)
