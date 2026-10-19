import re
from datetime import datetime, timedelta
from smtplib import SMTPException
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.tokens import email_verification_token
from teams.models import Roster, Team

User = get_user_model()

NYU_EMAIL = "ab1234@nyu.edu"
PASSWORD = "Tr1cky-passphrase-77"


def sign_up(client, email=NYU_EMAIL, password=PASSWORD, **extra):
    return client.post(
        reverse("accounts:register"),
        {"email": email, "password1": password, "password2": password, **extra},
    )


def link_from(message):
    """Pull the confirmation URL out of an email body."""
    match = re.search(r"https?://\S+/accounts/verify/\S+/", message.body)
    assert match, f"no confirmation link in: {message.body}"
    return match.group(0)


def path_of(link):
    return re.sub(r"^https?://[^/]+", "", link)


def make_verified_user(email=NYU_EMAIL, password=PASSWORD):
    return User.objects.create_user(username=email, email=email, password=password)


class RegistrationTests(TestCase):
    def test_register_page_loads(self):
        response = self.client.get(reverse("accounts:register"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NYU email")

    def test_non_nyu_email_is_rejected_with_the_epic_message(self):
        response = sign_up(self.client, email="someone@gmail.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please use your NYU ID")
        self.assertFalse(User.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_lookalike_domains_are_rejected(self):
        for email in ("ab1234@nyu.edu.evil.com", "ab1234@notnyu.edu", "ab1234@nyu.com", "nyu.edu@gmail.com"):
            with self.subTest(email=email):
                response = sign_up(self.client, email=email)
                self.assertContains(response, "Please use your NYU ID")
        self.assertFalse(User.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_nyu_email_creates_an_unverified_account_and_sends_one_email(self):
        response = sign_up(self.client)
        self.assertRedirects(response, reverse("accounts:check_email"))

        user = User.objects.get(email=NYU_EMAIL)
        self.assertFalse(user.is_active, "the account must be unusable until the email is confirmed")
        self.assertEqual(user.username, NYU_EMAIL)
        self.assertTrue(user.check_password(PASSWORD))

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [NYU_EMAIL])
        self.assertIn("/accounts/verify/", mail.outbox[0].body)

    def test_email_is_stored_lowercase(self):
        sign_up(self.client, email="  AB1234@NYU.EDU ")
        self.assertTrue(User.objects.filter(email="ab1234@nyu.edu").exists())
        self.assertEqual(mail.outbox[0].to, ["ab1234@nyu.edu"])

    def test_registration_does_not_log_the_user_in(self):
        sign_up(self.client)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_email_is_rejected(self):
        make_verified_user()
        response = sign_up(self.client, email=NYU_EMAIL.upper())
        self.assertContains(response, "already exists")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_duplicate_of_an_unverified_account_is_rejected(self):
        sign_up(self.client)
        response = sign_up(self.client, password="Another-str0ng-pass!")
        self.assertContains(response, "already exists")
        self.assertEqual(User.objects.count(), 1)
        # The original owner's password is untouched, so nobody can pre-register someone else's address.
        self.assertTrue(User.objects.get().check_password(PASSWORD))

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            reverse("accounts:register"),
            {"email": NYU_EMAIL, "password1": PASSWORD, "password2": "Different-pass-99"},
        )
        self.assertContains(response, "do not match")
        self.assertFalse(User.objects.exists())

    def test_weak_password_is_rejected(self):
        response = sign_up(self.client, password="password")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_account_is_rolled_back_if_the_email_cannot_be_sent(self):
        with mock.patch("accounts.views.send_mail", side_effect=SMTPException("down")):
            response = sign_up(self.client)
        self.assertContains(response, "could not send")
        self.assertFalse(User.objects.exists(), "no half-created account should be left behind")

    def test_signed_in_user_is_sent_away_from_register(self):
        self.client.force_login(make_verified_user())
        response = self.client.get(reverse("accounts:register"))
        self.assertRedirects(response, reverse("teams:list"), fetch_redirect_response=False)


class ConsoleEmailTests(TestCase):
    """With the console email backend the link is also logged on one line, because the printed email wraps it."""

    def test_link_is_logged_in_one_piece_when_using_the_console_backend(self):
        with mock.patch("accounts.views._console_email_in_use", return_value=True):
            with self.assertLogs("accounts.views", level="WARNING") as logs:
                sign_up(self.client)
        self.assertIn(link_from(mail.outbox[0]), logs.output[0])
        self.assertIn(NYU_EMAIL, logs.output[0])

    def test_link_is_never_logged_with_a_real_email_backend(self):
        with mock.patch("accounts.views._console_email_in_use", return_value=False):
            with self.assertNoLogs("accounts.views", level="DEBUG"):
                sign_up(self.client)
        self.assertEqual(len(mail.outbox), 1)


class VerificationTests(TestCase):
    def setUp(self):
        sign_up(self.client)
        self.user = User.objects.get(email=NYU_EMAIL)
        self.link = link_from(mail.outbox[0])

    def test_clicking_the_link_verifies_the_account(self):
        response = self.client.get(path_of(self.link))
        self.assertRedirects(response, reverse("login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_verification_shows_a_success_message(self):
        response = self.client.get(path_of(self.link), follow=True)
        self.assertContains(response, "verified")

    def test_link_does_not_log_anyone_in(self):
        self.client.get(path_of(self.link))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_link_can_only_be_used_once(self):
        self.client.get(path_of(self.link))
        response = self.client.get(path_of(self.link), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already verified")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_tampered_token_is_rejected(self):
        bad = self.link[:-2] + ("a/" if not self.link.endswith("a/") else "b/")
        response = self.client.get(path_of(bad))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "not valid", status_code=400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_garbage_link_is_rejected(self):
        for path in ("/accounts/verify/!!!/xyz/", "/accounts/verify/MQ/not-a-token/", "/accounts/verify/OTk5OQ/abc-def/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_expired_link_is_rejected(self):
        # Django's token clock uses naive datetimes; 4 days is past the 3-day default timeout.
        later = datetime.now() + timedelta(days=4)
        with mock.patch.object(email_verification_token, "_now", return_value=later):
            response = self.client.get(path_of(self.link))
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_link_for_one_user_does_not_verify_another(self):
        sign_up(self.client, email="zz9999@nyu.edu")
        other = User.objects.get(email="zz9999@nyu.edu")
        uid_of_other = urlsafe_base64_encode(force_bytes(other.pk))
        token_of_first = self.link.rstrip("/").rsplit("/", 1)[1]
        response = self.client.get(reverse("accounts:verify", args=[uid_of_other, token_of_first]))
        self.assertEqual(response.status_code, 400)
        other.refresh_from_db()
        self.assertFalse(other.is_active)

    def test_a_password_reset_token_cannot_verify_an_account(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.get(reverse("accounts:verify", args=[uid, token]))
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_an_account_nobody_confirms_stays_unusable(self):
        """A fake NYU address never receives the email, so the account never becomes active."""
        response = self.client.post(
            reverse("login"), {"username": NYU_EMAIL, "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


class LoginTests(TestCase):
    def test_verified_user_can_log_in_with_email(self):
        make_verified_user()
        response = self.client.post(reverse("login"), {"username": NYU_EMAIL, "password": PASSWORD})
        self.assertRedirects(response, reverse("teams:list"), fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)

    def test_email_login_ignores_case(self):
        make_verified_user()
        self.client.post(reverse("login"), {"username": NYU_EMAIL.upper(), "password": PASSWORD})
        self.assertIn("_auth_user_id", self.client.session)

    def test_existing_users_with_a_plain_username_can_log_in_by_email_or_username(self):
        User.objects.create_user(username="owner", email="owner@nyu.edu", password=PASSWORD)
        for identifier in ("owner", "owner@nyu.edu"):
            with self.subTest(identifier=identifier):
                self.client.logout()
                self.client.post(reverse("login"), {"username": identifier, "password": PASSWORD})
                self.assertIn("_auth_user_id", self.client.session)

    def test_unverified_user_is_told_to_confirm_their_email(self):
        sign_up(self.client)
        response = self.client.post(reverse("login"), {"username": NYU_EMAIL, "password": PASSWORD})
        self.assertContains(response, "not verified yet")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_password_gives_the_generic_error_even_for_unverified_accounts(self):
        sign_up(self.client)
        response = self.client.post(reverse("login"), {"username": NYU_EMAIL, "password": "wrong-password-1"})
        self.assertNotContains(response, "not verified yet")
        self.assertContains(response, "correct")

    def test_unknown_email_gives_the_generic_error(self):
        response = self.client.post(reverse("login"), {"username": "nobody@nyu.edu", "password": PASSWORD})
        self.assertNotContains(response, "not verified yet")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post_and_signs_out(self):
        self.client.force_login(make_verified_user())
        self.client.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_navigation_offers_register_when_signed_out(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, reverse("accounts:register"))


class ResendTests(TestCase):
    def test_resend_sends_a_working_link_to_an_unverified_account(self):
        sign_up(self.client)
        mail.outbox.clear()
        response = self.client.post(reverse("accounts:resend"), {"email": NYU_EMAIL})
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [NYU_EMAIL])

        self.client.get(path_of(link_from(mail.outbox[0])))
        self.assertTrue(User.objects.get(email=NYU_EMAIL).is_active)

    def test_resend_for_unknown_or_verified_addresses_sends_nothing_and_looks_identical(self):
        make_verified_user("done@nyu.edu")
        for email in ("nobody@nyu.edu", "done@nyu.edu"):
            with self.subTest(email=email):
                response = self.client.post(reverse("accounts:resend"), {"email": email}, follow=True)
                self.assertContains(response, "If that NYU address has an account waiting")
        self.assertEqual(len(mail.outbox), 0)

    def test_old_link_still_works_after_a_resend_until_it_is_used(self):
        sign_up(self.client)
        first = link_from(mail.outbox[0])
        self.client.post(reverse("accounts:resend"), {"email": NYU_EMAIL})
        self.client.get(path_of(link_from(mail.outbox[1])))
        # Once verified, the older link is dead as well.
        response = self.client.get(path_of(first), follow=True)
        self.assertContains(response, "already verified")


class EpicFlowTests(TestCase):
    def test_register_confirm_log_in_and_edit_profile(self):
        sign_up(self.client)
        self.client.get(path_of(link_from(mail.outbox[0])))
        self.client.post(reverse("login"), {"username": NYU_EMAIL, "password": PASSWORD})
        user = User.objects.get(email=NYU_EMAIL)

        edit_url = reverse("profiles:edit", args=[user.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 200)
        self.client.post(edit_url, {"first_name": "Alex", "last_name": "Lee"})
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("Alex", "Lee"))

    def test_captain_cannot_add_an_unverified_player_to_a_team(self):
        captain = User.objects.create_user(username="cap", email="cap@nyu.edu", password=PASSWORD)
        team = Team.objects.create(name="Violets", sport="Soccer", captain=captain)
        Roster.objects.create(team=team, player=captain, role=Roster.Role.CAPTAIN)

        sign_up(self.client)  # registers ab1234@nyu.edu, still unverified
        self.client.force_login(captain)
        response = self.client.post(reverse("teams:add_player", args=[team.pk]), {"email": NYU_EMAIL})
        self.assertContains(response, "No PlayNYU account")
        self.assertEqual(team.roster.count(), 1)

        # After the player confirms their email they can be added.
        self.client.logout()
        self.client.get(path_of(link_from(mail.outbox[0])))
        self.client.force_login(captain)
        self.client.post(reverse("teams:add_player", args=[team.pk]), {"email": NYU_EMAIL})
        self.assertEqual(team.roster.count(), 2)
