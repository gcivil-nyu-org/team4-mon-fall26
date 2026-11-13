from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from teams.models import Roster, Sport, Team

from .models import Message


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


def make_team(captain, name="Violets"):
    sport, _ = Sport.objects.get_or_create(name="Soccer")
    team = Team.objects.create(name=name, sport=sport, captain=captain)
    Roster.objects.create(team=team, player=captain, role=Roster.Role.CAPTAIN)
    return team


def add_player(team, user):
    return Roster.objects.create(team=team, player=user, role=Roster.Role.PLAYER)


class TeamThreadTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap")
        self.teammate = make_user("mate")
        self.outsider = make_user("outsider")
        self.team = make_team(self.captain)
        add_player(self.team, self.teammate)

    def thread_url(self):
        return reverse("chat:thread", args=[self.team.pk])

    def test_non_member_get_denied(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.thread_url())
        self.assertEqual(response.status_code, 404)

    def test_non_member_post_denied(self):
        self.client.force_login(self.outsider)
        response = self.client.post(self.thread_url(), {"body": "hi"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.exists())

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.thread_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_member_can_read_thread(self):
        Message.objects.create(team=self.team, author=self.captain, body="Hello team")
        self.client.force_login(self.teammate)
        response = self.client.get(self.thread_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hello team")

    def test_member_can_post(self):
        self.client.force_login(self.teammate)
        response = self.client.post(self.thread_url(), {"body": "See you Saturday"})
        self.assertRedirects(response, self.thread_url())
        message = Message.objects.get()
        self.assertEqual(message.body, "See you Saturday")
        self.assertEqual(message.author, self.teammate)
        self.assertEqual(message.team, self.team)
        self.assertFalse(message.is_flagged)

    def test_blank_body_rejected(self):
        self.client.force_login(self.teammate)
        response = self.client.post(self.thread_url(), {"body": "   "})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.exists())

    def test_body_over_500_chars_rejected(self):
        self.client.force_login(self.teammate)
        response = self.client.post(self.thread_url(), {"body": "x" * 501})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.exists())

    def test_body_at_500_chars_accepted(self):
        self.client.force_login(self.teammate)
        response = self.client.post(self.thread_url(), {"body": "x" * 500})
        self.assertRedirects(response, self.thread_url())
        self.assertEqual(Message.objects.get().body, "x" * 500)

    def test_model_max_length_validation(self):
        message = Message(team=self.team, author=self.captain, body="x" * 501)
        with self.assertRaises(ValidationError):
            message.full_clean()

    def test_empty_state_shown(self):
        self.client.force_login(self.teammate)
        response = self.client.get(self.thread_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No messages yet")


class FlagFlowTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap")
        self.teammate = make_user("mate")
        self.outsider = make_user("outsider")
        self.team = make_team(self.captain)
        add_player(self.team, self.teammate)
        self.message = Message.objects.create(
            team=self.team, author=self.teammate, body="Questionable post"
        )

    def flag_url(self):
        return reverse("chat:flag", args=[self.team.pk, self.message.pk])

    def test_any_roster_member_can_flag(self):
        self.client.force_login(self.captain)
        response = self.client.post(self.flag_url())
        self.assertRedirects(response, reverse("chat:thread", args=[self.team.pk]))
        self.message.refresh_from_db()
        self.assertTrue(self.message.is_flagged)

    def test_non_member_cannot_flag(self):
        self.client.force_login(self.outsider)
        response = self.client.post(self.flag_url())
        self.assertEqual(response.status_code, 404)
        self.message.refresh_from_db()
        self.assertFalse(self.message.is_flagged)

    def test_flag_idempotent(self):
        self.message.is_flagged = True
        self.message.save(update_fields=["is_flagged"])
        self.client.force_login(self.captain)
        response = self.client.post(self.flag_url())
        self.assertRedirects(response, reverse("chat:thread", args=[self.team.pk]))
        self.assertTrue(Message.objects.get(pk=self.message.pk).is_flagged)


class ModerationQueueTests(TestCase):
    def setUp(self):
        self.admin = make_user("leagueadmin")
        assign_role(self.admin, LEAGUE_ADMIN_ROLE)
        self.captain = make_user("cap")
        self.team = make_team(self.captain)
        self.flagged = Message.objects.create(
            team=self.team,
            author=self.captain,
            body="Flagged post",
            is_flagged=True,
        )
        self.clean = Message.objects.create(
            team=self.team, author=self.captain, body="Fine post"
        )

    def queue_url(self):
        return reverse("chat:moderation_queue")

    def moderate_url(self):
        return reverse("chat:moderate", args=[self.flagged.pk])

    def test_non_admin_denied(self):
        self.client.force_login(self.captain)
        response = self.client.get(self.queue_url())
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_moderate(self):
        self.client.force_login(self.captain)
        response = self.client.post(self.moderate_url(), {"action": "delete"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Message.objects.filter(pk=self.flagged.pk).exists())

    def test_admin_sees_only_flagged(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.queue_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Flagged post")
        self.assertNotContains(response, "Fine post")

    def test_admin_dismiss_keeps_message(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.moderate_url(), {"action": "dismiss"})
        self.assertRedirects(response, self.queue_url())
        message = Message.objects.get(pk=self.flagged.pk)
        self.assertFalse(message.is_flagged)

    def test_admin_delete_removes_message(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.moderate_url(), {"action": "delete"})
        self.assertRedirects(response, self.queue_url())
        self.assertFalse(Message.objects.filter(pk=self.flagged.pk).exists())
        self.assertTrue(Message.objects.filter(pk=self.clean.pk).exists())

    def test_empty_queue_state(self):
        Message.objects.filter(is_flagged=True).delete()
        self.client.force_login(self.admin)
        response = self.client.get(self.queue_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No flagged messages")
