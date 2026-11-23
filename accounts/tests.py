import re
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from profiles.models import PlayerProfile

from .models import RateLimitBucket
from .tokens import email_verification_token

VALID = {
    "email": "SP1234@NYU.edu",
    "first_name": "Sam",
    "last_name": "Park",
    "password1": "Str0ng-pass-2026",
    "password2": "Str0ng-pass-2026",
}
EMAIL = "sp1234@nyu.edu"


def link_from(message):
    return re.search(r"http://testserver(/accounts/verify/\S+/)", message.body).group(1)


class SignUpTests(TestCase):
    url = reverse("accounts:signup")

    def test_page_loads(self):
        self.assertContains(self.client.get(self.url), 'name="email"')

    def test_signup_creates_inactive_user_and_emails_a_link(self):
        response = self.client.post(self.url, VALID)
        self.assertRedirects(response, reverse("accounts:check_email"))
        user = get_user_model().objects.get(email=EMAIL)
        self.assertEqual(user.username, EMAIL)
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [EMAIL])
        self.assertIn("/accounts/verify/", mail.outbox[0].body)

    def test_check_email_screen_names_the_address(self):
        response = self.client.post(self.url, VALID, follow=True)
        self.assertContains(response, "Check your email")
        self.assertContains(response, EMAIL)

    def test_non_nyu_email_rejected(self):
        response = self.client.post(self.url, {**VALID, "email": "sam@gmail.com"})
        self.assertContains(response, "Please use your NYU ID")
        self.assertFalse(get_user_model().objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_duplicate_email_rejected(self):
        get_user_model().objects.create_user(EMAIL, EMAIL, "x-pass-12345")
        response = self.client.post(self.url, {**VALID, "email": "Sp1234@nyu.edu"})
        self.assertContains(response, "An account with this email already exists.")
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_password_problems_rejected(self):
        for data in (
            {**VALID, "password2": "different-pass-1"},
            {**VALID, "password1": "123", "password2": "123"},
        ):
            response = self.client.post(self.url, data)
            self.assertContains(response, "Your account was not created.")
        self.assertFalse(get_user_model().objects.exists())

    def test_signed_in_user_is_redirected(self):
        user = get_user_model().objects.create_user(
            "ab1234@nyu.edu", "ab1234@nyu.edu", "x-pass-12345"
        )
        self.client.force_login(user)
        self.assertRedirects(self.client.get(self.url), reverse("core:home"))


class VerifyTests(TestCase):
    def setUp(self):
        self.client.post(reverse("accounts:signup"), VALID)
        self.user = get_user_model().objects.get(email=EMAIL)
        self.link = link_from(mail.outbox[0])

    def test_confirmed_page_does_not_show_signed_in_menu(self):
        response = self.client.get(self.link)
        self.assertNotContains(response, "Log out")
        self.assertContains(response, "Log in")

    def test_link_activates_account_and_creates_profile(self):
        response = self.client.get(self.link)
        self.assertContains(response, "Email confirmed")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(PlayerProfile.objects.get(user=self.user).net_id, "sp1234")
        self.assertTrue(self.user.groups.filter(name="Casual Player").exists())

    def test_link_works_only_once(self):
        self.client.get(self.link)
        response = self.client.get(self.link)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "expired or is not valid", status_code=400)

    def test_tampered_link_is_rejected(self):
        response = self.client.get(self.link[:-3] + "xx/")
        self.assertContains(response, "expired or is not valid", status_code=400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_unknown_user_link_is_rejected(self):
        response = self.client.get(
            reverse("accounts:verify", args=["bm9wZQ", "abc-123"])
        )
        self.assertContains(response, "expired or is not valid", status_code=400)

    def test_link_expires_after_24_hours(self):
        later = datetime.now() + timedelta(hours=25)
        with mock.patch.object(email_verification_token, "_now", return_value=later):
            response = self.client.get(self.link)
        self.assertContains(response, "expired or is not valid", status_code=400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_link_still_works_within_24_hours(self):
        later = datetime.now() + timedelta(hours=23)
        with mock.patch.object(email_verification_token, "_now", return_value=later):
            response = self.client.get(self.link)
        self.assertContains(response, "Email confirmed")


class UnverifiedSignUpTests(TestCase):
    """Only the inbox owner chooses the password (#302)."""

    CLAIM = {
        "first_name": "Real",
        "last_name": "Owner",
        "password1": "Own3r-pass-2026",
        "password2": "Own3r-pass-2026",
    }

    def setUp(self):
        # Someone else signs up with this email first, in their own browser.
        self.client_class().post(reverse("accounts:signup"), VALID)

    def user(self):
        return get_user_model().objects.get(email=EMAIL)

    def test_link_in_another_browser_asks_for_a_password(self):
        link = link_from(mail.outbox[0])
        response = self.client.get(link)
        self.assertContains(response, "Finish signing up")
        self.assertNotContains(response, "already on a team")
        self.assertFalse(self.user().is_active)

        response = self.client.post(link, self.CLAIM)
        self.assertRedirects(response, reverse("core:home"))
        user = self.user()
        self.assertTrue(user.is_active)
        self.assertEqual(user.first_name, "Real")
        self.assertTrue(user.check_password(self.CLAIM["password1"]))
        self.assertFalse(user.check_password(VALID["password1"]))
        self.assertEqual(self.client.get(link).status_code, 400)

    def test_owner_can_sign_up_and_still_sets_the_password_from_the_link(self):
        data = {**VALID, **self.CLAIM}
        response = self.client.post(reverse("accounts:signup"), data)
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertEqual(get_user_model().objects.count(), 1)
        link = link_from(mail.outbox[-1])
        self.assertContains(self.client.get(link), "Finish signing up")
        self.client.post(link, self.CLAIM)
        self.assertTrue(self.user().check_password(self.CLAIM["password1"]))

    def test_second_sign_up_does_not_change_the_first(self):
        data = {**VALID, **self.CLAIM}
        self.client.post(reverse("accounts:signup"), data)
        self.assertTrue(self.user().check_password(VALID["password1"]))
        self.assertEqual(self.user().first_name, "Sam")

    def test_deactivated_account_cannot_sign_up_again(self):
        link = link_from(mail.outbox[0])
        PlayerProfile.objects.create(user=self.user())
        response = self.client.post(reverse("accounts:signup"), VALID)
        self.assertContains(response, "An account with this email already exists.")
        # Nor can an old link or a new one bring it back.
        self.assertEqual(self.client.get(link).status_code, 400)
        self.assertEqual(self.client.post(link, self.CLAIM).status_code, 400)
        self.client.post(reverse("accounts:resend"), {"email": EMAIL})
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(self.user().is_active)


class ResendTests(TestCase):
    url = reverse("accounts:resend")

    def setUp(self):
        self.client.post(reverse("accounts:signup"), VALID)
        mail.outbox.clear()

    def test_resend_sends_a_new_working_link(self):
        response = self.client.post(self.url, {"email": EMAIL.upper()})
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(
            self.client.get(link_from(mail.outbox[0])), "Email confirmed"
        )

    def test_unknown_or_active_email_sends_nothing_but_looks_the_same(self):
        active = get_user_model().objects.create_user(
            "cd5678@nyu.edu", "cd5678@nyu.edu", "x-pass-12345"
        )
        for email in ("zz9999@nyu.edu", active.email):
            response = self.client.post(self.url, {"email": email})
            self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_page_loads(self):
        self.assertContains(self.client.get(self.url), "Get a new confirmation link")

    def test_resend_rate_limit_after_three_requests(self):
        # Signup in setUp already consumes one of the three email slots.
        for _ in range(2):
            response = self.client.post(self.url, {"email": EMAIL})
            self.assertRedirects(response, reverse("accounts:check_email"))

        self.assertEqual(len(mail.outbox), 2)

        response = self.client.post(self.url, {"email": EMAIL})
        self.assertRedirects(
            response,
            reverse("accounts:check_email"),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(self.client.session["verification_rate_limited"])


class LoginTests(TestCase):
    url = reverse("login")

    def setUp(self):
        self.client.post(reverse("accounts:signup"), VALID)
        self.user = get_user_model().objects.get(email=EMAIL)

    def test_unverified_user_is_redirected_to_confirmation_flow(self):
        response = self.client.post(
            self.url, {"username": EMAIL, "password": VALID["password1"]}
        )
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_password_does_not_reveal_unverified_account(self):
        response = self.client.post(
            self.url, {"username": EMAIL, "password": "wrong-pass-123"}
        )
        self.assertNotContains(response, "Please confirm your email first.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verified_user_logs_in_with_email_in_any_case(self):
        self.client.get(link_from(mail.outbox[0]))
        response = self.client.post(
            self.url, {"username": "SP1234@nyu.edu", "password": VALID["password1"]}
        )
        self.assertRedirects(response, reverse("core:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_wrong_password_error_says_nyu_email(self):
        # #291: the field is "NYU email", so the error must not say "username".
        self.client.get(link_from(mail.outbox[0]))
        response = self.client.post(
            self.url, {"username": EMAIL, "password": "wrong-pass-123"}
        )
        self.assertContains(response, "The NYU email or password is incorrect.")
        self.assertNotContains(response, "correct username")

    def test_signed_in_user_opening_login_goes_home(self):
        # #271: no stale login form for a user who is already signed in.
        self.client.get(link_from(mail.outbox[0]))
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(self.url), reverse("core:home"))

    def test_login_page_links_to_signup_and_resend(self):
        response = self.client.get(self.url)
        self.assertContains(response, reverse("accounts:signup"))
        self.assertContains(response, reverse("accounts:resend"))

    def test_login_rate_limit_after_five_failed_attempts(self):
        for _ in range(5):
            response = self.client.post(
                self.url, {"username": EMAIL, "password": "wrong-password"}
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            self.url, {"username": EMAIL, "password": VALID["password1"]}
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_clears_failed_attempts(self):
        self.client.get(link_from(mail.outbox[0]))

        for _ in range(2):
            self.client.post(
                self.url, {"username": EMAIL, "password": "wrong-password"}
            )

        response = self.client.post(
            self.url, {"username": EMAIL, "password": VALID["password1"]}
        )
        self.assertRedirects(response, reverse("core:home"))
        self.client.logout()

        for _ in range(3):
            self.client.post(
                self.url, {"username": EMAIL, "password": "wrong-password"}
            )

        response = self.client.post(
            self.url, {"username": EMAIL, "password": VALID["password1"]}
        )
        self.assertRedirects(response, reverse("core:home"))

    def test_login_rate_limit_expires(self):
        for _ in range(settings.LOGIN_RATE_LIMIT_EMAIL_ATTEMPTS):
            self.client.post(
                self.url, {"username": EMAIL, "password": "wrong-password"}
            )

        response = self.client.post(
            self.url, {"username": EMAIL, "password": VALID["password1"]}
        )
        self.assertEqual(response.status_code, 429)

        RateLimitBucket.objects.update(
            window_started_at=timezone.now()
            - timedelta(seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS + 1)
        )

        self.client.get(link_from(mail.outbox[0]))
        response = self.client.post(
            self.url, {"username": EMAIL, "password": VALID["password1"]}
        )
        self.assertRedirects(response, reverse("core:home"))

    def test_login_rate_limit_by_ip(self):
        for i in range(settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS):
            response = self.client.post(
                self.url,
                {
                    "username": f"unknown{i}@nyu.edu",
                    "password": "wrong-password",
                },
                REMOTE_ADDR="192.0.2.10",
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            self.url,
            {"username": EMAIL, "password": VALID["password1"]},
            REMOTE_ADDR="192.0.2.10",
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertNotIn("_auth_user_id", self.client.session)


class NetIdFromEmailTests(TestCase):
    def verify(self, email):
        self.client.post(reverse("accounts:signup"), {**VALID, "email": email})
        self.client.get(link_from(mail.outbox[-1]))
        return PlayerProfile.objects.get(user__email=email.lower())

    def test_netid_style_email_prefills_net_id(self):
        self.assertEqual(self.verify("ab1234@nyu.edu").net_id, "ab1234")

    def test_other_email_styles_leave_net_id_blank(self):
        self.assertIsNone(self.verify("jane.doe@nyu.edu").net_id)

    def test_owner_gets_the_net_id_back(self):
        other = get_user_model().objects.create_user("x", "x@nyu.edu", "x-pass-12345")
        PlayerProfile.objects.create(user=other, net_id="ab1234")
        self.assertEqual(self.verify("ab1234@nyu.edu").net_id, "ab1234")
        self.assertIsNone(PlayerProfile.objects.get(user=other).net_id)
