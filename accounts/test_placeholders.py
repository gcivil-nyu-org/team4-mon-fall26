"""Placeholder accounts (#219): captains add players by email before sign-up."""

import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import BadHeaderError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from profiles.models import PlayerProfile
from teams.models import Roster, Sport, Team

from .models import PendingAccount
from . import placeholders
from .placeholders import find_user_by_email, placeholder_for, send_invite_email
from .tokens import email_verification_token

NEW = "np1234@nyu.edu"
SIGNUP = {
    "email": "NP1234@nyu.edu",
    "first_name": "Nia",
    "last_name": "Patel",
    "password1": "Str0ng-pass-2026",
    "password2": "Str0ng-pass-2026",
}


def make_user(email, **extra):
    return get_user_model().objects.create_user(
        username=email, email=email, password="pass12345!", **extra
    )


def make_team(captain, name="Violets"):
    sport, _ = Sport.objects.get_or_create(name="Soccer")
    team = Team.objects.create(name=name, sport=sport, captain=captain)
    Roster.objects.create(team=team, player=captain, role=Roster.Role.CAPTAIN)
    return team


def verify_link(message):
    return re.search(r"http://testserver(/accounts/verify/\S+/)", message.body).group(1)


def manual_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return reverse(
        "accounts:verify", args=[uid, email_verification_token.make_token(user)]
    )


class PlaceholderForTests(TestCase):
    def test_creates_inactive_user_with_unusable_password(self):
        captain = make_user("cap@nyu.edu")
        user, created = placeholder_for(
            "  NP1234@NYU.edu ", first_name="Nia", invited_by=captain
        )
        self.assertTrue(created)
        self.assertEqual(user.username, NEW)
        self.assertEqual(user.email, NEW)
        self.assertEqual(user.first_name, "Nia")
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(PendingAccount.objects.get(user=user).invited_by, captain)

    def test_returns_existing_user_unchanged(self):
        existing = make_user(NEW, first_name="Old")
        user, created = placeholder_for(NEW.upper(), first_name="New")
        self.assertFalse(created)
        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(user.first_name, "Old")
        self.assertFalse(PendingAccount.objects.exists())

    def test_second_call_does_not_duplicate(self):
        first, _ = placeholder_for(NEW)
        second, created = placeholder_for(NEW)
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PendingAccount.objects.count(), 1)

    def test_lost_create_race_returns_the_other_user(self):
        # Another request creates the user between the lookup and the create.
        real_find = placeholders.find_user_by_email
        calls = []

        def find(email):
            calls.append(email)
            if len(calls) == 1:
                make_user(NEW, first_name="Racer")
                return None
            return real_find(email)

        with mock.patch.object(placeholders, "find_user_by_email", find):
            user, created = placeholder_for(NEW, first_name="Late")
        self.assertFalse(created)
        self.assertEqual(user.first_name, "Racer")
        self.assertFalse(PendingAccount.objects.exists())
        # The savepoint keeps the surrounding transaction usable.
        self.assertEqual(get_user_model().objects.filter(email=NEW).count(), 1)

    def test_create_error_without_a_user_is_raised(self):
        with mock.patch.object(
            get_user_model(), "save", side_effect=IntegrityError("boom")
        ):
            with self.assertRaises(IntegrityError):
                placeholder_for(NEW)

    def test_find_user_by_email_matches_email_or_username(self):
        user = make_user(NEW)
        self.assertEqual(find_user_by_email("  NP1234@NYU.edu "), user)
        other = get_user_model().objects.create_user(
            username="ab1@nyu.edu", email="", password="x"
        )
        self.assertEqual(find_user_by_email("AB1@nyu.edu"), other)
        self.assertIsNone(find_user_by_email("nobody@nyu.edu"))

    def test_invite_subject_has_no_newline(self):
        captain = make_user("cap@nyu.edu")
        team = make_team(captain, name="Evil\r\nBcc: x@nyu.edu")
        user, _ = placeholder_for(NEW)
        send_invite_email("https://play.example.com", user, team, captain)
        self.assertEqual(
            mail.outbox[0].subject, "You were added to Evil Bcc: x@nyu.edu on PlayNYU"
        )

    def test_invite_email_with_base_url(self):
        captain = make_user("cap@nyu.edu", first_name="Cam", last_name="Lee")
        team = make_team(captain)
        user, _ = placeholder_for(NEW)
        send_invite_email("https://play.example.com/", user, team, captain)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("Cam Lee added you to Violets", body)
        self.assertIn("https://play.example.com/accounts/signup/", body)


class AddPlayerByEmailTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap@nyu.edu", first_name="Cam", last_name="Lee")
        self.team = make_team(self.captain)
        self.url = reverse("teams:add_player", args=[self.team.pk])
        self.client.force_login(self.captain)

    def test_new_email_creates_placeholder_on_roster_and_invites_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url, {"email": "NP1234@nyu.edu"}, follow=True
            )
        self.assertRedirects(response, reverse("teams:detail", args=[self.team.pk]))
        self.assertContains(response, "sign up with that email")
        user = get_user_model().objects.get(email=NEW)
        self.assertFalse(user.is_active)
        self.assertTrue(PendingAccount.objects.filter(user=user).exists())
        self.assertTrue(Roster.objects.filter(team=self.team, player=user).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [NEW])
        self.assertIn("Violets", mail.outbox[0].subject)
        self.assertIn("Cam Lee added you to Violets", mail.outbox[0].body)
        self.assertIn("http://testserver/accounts/signup/", mail.outbox[0].body)

    def test_existing_placeholder_on_another_team_gets_no_second_invite(self):
        user, _ = placeholder_for(NEW)
        other = make_team(make_user("cap2@nyu.edu"), name="Bobcats")
        Roster.objects.create(team=other, player=user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, {"email": NEW})
        self.assertTrue(Roster.objects.filter(team=self.team, player=user).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_unverified_user_is_added(self):
        user = make_user(NEW, is_active=False)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, {"email": NEW}, follow=True)
        self.assertTrue(Roster.objects.filter(team=self.team, player=user).exists())
        self.assertFalse(PendingAccount.objects.exists())
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, "sign up with that email")

    def test_active_user_is_added_with_plain_message(self):
        user = make_user(NEW)
        response = self.client.post(self.url, {"email": NEW}, follow=True)
        self.assertTrue(Roster.objects.filter(team=self.team, player=user).exists())
        self.assertContains(response, f"Added {NEW} to Violets.")
        self.assertNotContains(response, "sign up with that email")
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_errors_do_not_reveal_whether_an_account_exists(self):
        make_user("known@nyu.edu")
        for email in ("known@nyu.edu", "unknown@nyu.edu"):
            response = self.client.post(self.url, {"email": email})
            self.assertNotContains(response, "No PlayNYU account", status_code=302)
            self.assertEqual(response.status_code, 302)

    @override_settings(INVITE_RATE_LIMIT_ATTEMPTS=2)
    def test_every_add_counts_toward_the_rate_limit(self):
        existing = make_user("known@nyu.edu")
        later = make_user("later@nyu.edu")
        with self.captureOnCommitCallbacks(execute=True):
            # An existing user and a new email each use one slot.
            self.client.post(self.url, {"email": "known@nyu.edu"})
            self.client.post(self.url, {"email": "new0@nyu.edu"})
            responses = [
                self.client.post(self.url, {"email": email})
                for email in ("later@nyu.edu", "new1@nyu.edu")
            ]
        self.assertTrue(Roster.objects.filter(team=self.team, player=existing).exists())
        self.assertEqual(len(mail.outbox), 1)
        # After the limit, both get the same error, so it can't reveal an account.
        error = "You&#x27;ve added a lot of players today. Try again tomorrow."
        for response in responses:
            self.assertContains(response, error)
        self.assertEqual(
            responses[0].context["form"].errors, responses[1].context["form"].errors
        )
        self.assertFalse(Roster.objects.filter(team=self.team, player=later).exists())
        self.assertFalse(get_user_model().objects.filter(email="new1@nyu.edu").exists())

    @override_settings(INVITE_RATE_LIMIT_ATTEMPTS=1)
    def test_non_nyu_email_does_not_count(self):
        self.client.post(self.url, {"email": "someone@example.com"})
        response = self.client.post(self.url, {"email": NEW})
        self.assertEqual(response.status_code, 302)

    def test_smtp_failure_is_logged_and_add_still_succeeds(self):
        with mock.patch(
            "accounts.placeholders.send_mail", side_effect=OSError("smtp down")
        ):
            with self.assertLogs("accounts.placeholders", "ERROR") as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(self.url, {"email": NEW}, follow=True)
        self.assertRedirects(response, reverse("teams:detail", args=[self.team.pk]))
        self.assertContains(response, "sign up with that email")
        user = get_user_model().objects.get(email=NEW)
        self.assertTrue(Roster.objects.filter(team=self.team, player=user).exists())
        message = logs.records[0].getMessage()
        self.assertEqual(message, f"Invite email failed for user {user.pk}")

    def test_bad_header_is_logged_and_add_still_succeeds(self):
        with mock.patch(
            "accounts.placeholders.send_mail", side_effect=BadHeaderError("newline")
        ):
            with self.assertLogs("accounts.placeholders", "ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(self.url, {"email": NEW})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(email=NEW).exists())

    def test_full_roster_rejects_new_email_without_creating_user(self):
        with mock.patch.object(Team, "DEFAULT_MAX_ROSTER_SIZE", 1):
            response = self.client.post(self.url, {"email": NEW})
        self.assertContains(response, "The roster is full")
        self.assertFalse(get_user_model().objects.filter(email=NEW).exists())


class RosterBadgeTests(TestCase):
    def test_inactive_player_has_badge_and_no_profile_link(self):
        captain = make_user("cap@nyu.edu")
        team = make_team(captain)
        user, _ = placeholder_for(NEW)
        Roster.objects.create(team=team, player=user)
        self.client.force_login(captain)
        response = self.client.get(reverse("teams:detail", args=[team.pk]))
        self.assertContains(response, "Not signed up yet", count=1)
        self.assertContains(response, NEW)
        self.assertNotContains(
            response, reverse("profiles:detail", args=[user.pk]) + '"'
        )
        self.assertContains(response, reverse("profiles:detail", args=[captain.pk]))


CLAIM = {
    "first_name": "Nia",
    "last_name": "Patel",
    "password1": "Vict1m-own-pass",
    "password2": "Vict1m-own-pass",
}


class ClaimTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap@nyu.edu")
        self.team = make_team(self.captain)
        self.placeholder, _ = placeholder_for(
            NEW, first_name="Old", invited_by=self.captain
        )
        Roster.objects.create(team=self.team, player=self.placeholder)

    def user(self):
        return get_user_model().objects.get(pk=self.placeholder.pk)

    def test_claim_flow_end_to_end(self):
        response = self.client.post(reverse("accounts:signup"), SIGNUP)
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertEqual(get_user_model().objects.filter(email=NEW).count(), 1)
        # Sign-up changes nothing on the placeholder; it only sends the link.
        user = self.user()
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.first_name, "Old")
        self.assertTrue(PendingAccount.objects.filter(user=user).exists())

        link = verify_link(mail.outbox[0])
        page = self.client.get(link)
        self.assertContains(page, "Finish signing up")
        self.assertContains(page, 'value="Old"')
        self.assertFalse(self.user().is_active)

        response = self.client.post(link, CLAIM)
        self.assertContains(response, "Email confirmed")
        user = self.user()
        self.assertTrue(user.is_active)
        self.assertEqual(user.first_name, "Nia")
        self.assertTrue(user.check_password(CLAIM["password1"]))
        self.assertFalse(PendingAccount.objects.filter(user=user).exists())
        self.assertTrue(PlayerProfile.objects.filter(user=user).exists())
        self.assertTrue(user.groups.filter(name="Casual Player").exists())
        self.assertTrue(Roster.objects.filter(team=self.team, player=user).exists())
        self.assertTrue(self.client.login(username=NEW, password=CLAIM["password1"]))

    def test_attacker_sign_up_leaves_the_account_with_the_inbox_owner(self):
        attacker = {
            **SIGNUP,
            "password1": "Attack3r-pass-26",
            "password2": "Attack3r-pass-26",
        }
        self.client.post(reverse("accounts:signup"), attacker)
        self.assertFalse(self.user().check_password("Attack3r-pass-26"))

        # The victim opens the unexpected email and sets their own password.
        self.client.post(verify_link(mail.outbox[0]), CLAIM)
        user = self.user()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(CLAIM["password1"]))
        self.assertFalse(user.check_password("Attack3r-pass-26"))
        self.assertFalse(self.client.login(username=NEW, password="Attack3r-pass-26"))

    def test_claim_page_validates_passwords(self):
        link = manual_link(self.placeholder)
        for data in (
            {**CLAIM, "password2": "Different-pass-1"},
            {**CLAIM, "password1": "123", "password2": "123"},
            {**CLAIM, "password1": "np1234nyu", "password2": "np1234nyu"},
        ):
            response = self.client.post(link, data)
            self.assertContains(response, "Your account is not active yet.")
        user = self.user()
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertTrue(PendingAccount.objects.filter(user=user).exists())

    def test_claim_link_works_once(self):
        link = manual_link(self.placeholder)
        self.client.post(link, CLAIM)
        second = {**CLAIM, "password1": "Sec0nd-pass-26", "password2": "Sec0nd-pass-26"}
        for response in (self.client.get(link), self.client.post(link, second)):
            self.assertEqual(response.status_code, 400)
        self.assertTrue(self.user().check_password(CLAIM["password1"]))

    def test_bad_token_is_refused_on_post(self):
        link = manual_link(self.placeholder)
        response = self.client.post(link[:-3] + "xx/", CLAIM)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.user().is_active)

    def test_claimed_account_cannot_sign_up_again(self):
        self.client.post(manual_link(self.placeholder), CLAIM)
        response = self.client.post(reverse("accounts:signup"), SIGNUP)
        self.assertContains(response, "An account with this email already exists.")

    def test_resend_sends_the_claim_link(self):
        response = self.client.post(reverse("accounts:resend"), {"email": NEW})
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(
            self.client.get(verify_link(mail.outbox[0])), "Finish signing up"
        )

    def test_user_without_password_and_not_placeholder_cannot_be_activated(self):
        user = make_user("nopass@nyu.edu", is_active=False)
        user.set_unusable_password()
        user.save()
        response = self.client.get(manual_link(user))
        self.assertEqual(response.status_code, 400)
        self.client.post(reverse("accounts:resend"), {"email": "nopass@nyu.edu"})
        self.assertEqual(len(mail.outbox), 0)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_unclaimed_placeholder_cannot_log_in(self):
        response = self.client.post(reverse("login"), {"username": NEW, "password": ""})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response.status_code, 200)
