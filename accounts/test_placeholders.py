"""Placeholder accounts (#219): captains add players by email before sign-up."""

import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from teams.models import Roster, Sport, Team

from .models import PendingAccount
from .placeholders import placeholder_for, send_invite_email
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


class ClaimTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap@nyu.edu")
        self.team = make_team(self.captain)
        self.placeholder, _ = placeholder_for(NEW, invited_by=self.captain)
        Roster.objects.create(team=self.team, player=self.placeholder)

    def test_claim_flow_end_to_end(self):
        response = self.client.post(reverse("accounts:signup"), SIGNUP)
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertEqual(get_user_model().objects.filter(email=NEW).count(), 1)
        user = get_user_model().objects.get(email=NEW)
        self.assertEqual(user.pk, self.placeholder.pk)
        self.assertFalse(user.is_active)
        self.assertEqual(user.first_name, "Nia")
        self.assertTrue(user.check_password(SIGNUP["password1"]))
        # Not claimed until the email link is opened.
        self.assertTrue(PendingAccount.objects.filter(user=user).exists())

        response = self.client.get(verify_link(mail.outbox[0]))
        self.assertContains(response, "Email confirmed")
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(PendingAccount.objects.filter(user=user).exists())
        self.assertTrue(Roster.objects.filter(team=self.team, player=user).exists())
        self.assertTrue(self.client.login(username=NEW, password=SIGNUP["password1"]))

    def test_claimed_account_cannot_sign_up_again(self):
        self.client.post(reverse("accounts:signup"), SIGNUP)
        self.client.get(verify_link(mail.outbox[0]))
        response = self.client.post(reverse("accounts:signup"), SIGNUP)
        self.assertContains(response, "An account with this email already exists.")

    def test_unclaimed_placeholder_cannot_be_activated_by_a_link(self):
        response = self.client.get(manual_link(self.placeholder))
        self.assertEqual(response.status_code, 400)
        self.placeholder.refresh_from_db()
        self.assertFalse(self.placeholder.is_active)

    def test_resend_skips_unclaimed_placeholder(self):
        response = self.client.post(reverse("accounts:resend"), {"email": NEW})
        self.assertRedirects(response, reverse("accounts:check_email"))
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_works_after_sign_up(self):
        self.client.post(reverse("accounts:signup"), SIGNUP)
        self.client.post(reverse("accounts:resend"), {"email": NEW})
        self.assertEqual(len(mail.outbox), 2)

    def test_second_claim_invalidates_the_first_link(self):
        self.client.post(reverse("accounts:signup"), SIGNUP)
        first = verify_link(mail.outbox[0])
        self.client.post(
            reverse("accounts:signup"),
            {**SIGNUP, "password1": "An0ther-pass-26", "password2": "An0ther-pass-26"},
        )
        second = verify_link(mail.outbox[1])

        response = self.client.get(first)
        self.assertEqual(response.status_code, 400)
        self.assertContains(self.client.get(second), "Email confirmed")
        user = get_user_model().objects.get(pk=self.placeholder.pk)
        self.assertTrue(user.check_password("An0ther-pass-26"))

    def test_unclaimed_placeholder_cannot_log_in(self):
        response = self.client.post(reverse("login"), {"username": NEW, "password": ""})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response.status_code, 200)
