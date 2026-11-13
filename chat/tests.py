from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from teams.models import Roster, Sport, Team

from .models import Message
from .templatetags.chat_tags import home_chat_rows


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


class TeamPageChatLinkTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap")
        self.teammate = make_user("mate")
        self.team = make_team(self.captain)
        add_player(self.team, self.teammate)
        self.team_url = reverse("teams:detail", args=[self.team.pk])
        self.thread_url = reverse("chat:thread", args=[self.team.pk])

    def test_members_see_chat_link(self):
        for member in (self.captain, self.teammate):
            self.client.force_login(member)
            response = self.client.get(self.team_url)
            self.assertContains(response, f'href="{self.thread_url}"')
            self.assertContains(response, "Team chat")

    def test_non_member_gets_no_chat_link(self):
        self.client.force_login(make_user("outsider"))
        response = self.client.get(self.team_url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.thread_url, response.content.decode())


class HomeChatPanelTests(TestCase):
    def setUp(self):
        self.user = make_user("alex")
        self.mate = make_user("sam")
        self.mate.first_name = "Sam"
        self.mate.save()
        self.home_url = reverse("core:home")

    def say(self, team, author, body, minutes_ago=0):
        message = Message.objects.create(team=team, author=author, body=body)
        if minutes_ago:
            Message.objects.filter(pk=message.pk).update(
                created_at=timezone.now() - timedelta(minutes=minutes_ago)
            )
            message.refresh_from_db()
        return message

    def rows(self, user=None):
        return home_chat_rows(user or self.user)

    def test_dashboard_renders_panel(self):
        team = make_team(self.user)
        add_player(team, self.mate)
        self.say(team, self.mate, "Bring the cones", minutes_ago=5)
        self.client.force_login(self.user)
        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "chat/_home_panel.html")
        self.assertContains(response, "Sam: Bring the cones")
        self.assertContains(response, "5\xa0minutes ago")
        self.assertContains(
            response, f'href="{reverse("chat:thread", args=[team.pk])}"'
        )

    def test_latest_message_wins(self):
        team = make_team(self.user)
        add_player(team, self.mate)
        self.say(team, self.mate, "Old news", minutes_ago=90)
        self.say(team, self.user, "Fresh news", minutes_ago=2)
        (row,) = self.rows()
        self.assertEqual(row["team"], team)
        self.assertEqual(row["preview"], "alex: Fresh news")
        self.assertEqual(row["time_label"], "2\xa0minutes ago")

    def test_new_message_says_just_now(self):
        team = make_team(self.user)
        self.say(team, self.user, "Hi")
        self.assertEqual(self.rows()[0]["time_label"], "Just now")

    def test_long_message_truncated_to_60_characters(self):
        team = make_team(self.user)
        add_player(team, self.mate)
        self.say(team, self.mate, "a" * 61)
        self.say(make_team(self.mate, name="Exact"), self.mate, "b" * 60)
        self.assertEqual(self.rows()[0]["preview"], "Sam: " + "a" * 60 + "…")
        self.assertEqual(self.rows(self.mate)[0]["preview"], "Sam: " + "b" * 60)

    def test_one_row_per_team(self):
        first = make_team(self.user, name="Violets")
        second = make_team(self.mate, name="Bobcats")
        add_player(second, self.user)
        self.say(first, self.user, "First team")
        self.say(second, self.mate, "Second team")
        rows = self.rows()
        self.assertEqual([row["team"] for row in rows], [second, first])
        self.assertEqual(
            [row["preview"] for row in rows],
            ["Sam: Second team", "alex: First team"],
        )

    def test_team_without_messages(self):
        team = make_team(self.user)
        (row,) = self.rows()
        self.assertIsNone(row["message"])
        self.client.force_login(self.user)
        response = self.client.get(self.home_url)
        self.assertContains(response, "No messages yet. Say hello.")
        self.assertContains(
            response, f'href="{reverse("chat:thread", args=[team.pk])}"'
        )

    def test_user_without_teams(self):
        self.assertEqual(self.rows(), [])
        self.client.force_login(self.user)
        response = self.client.get(self.home_url)
        self.assertContains(response, "Join a team to chat with teammates.")

    def test_other_teams_messages_stay_hidden(self):
        mine = make_team(self.user, name="Violets")
        theirs = make_team(self.mate, name="Bobcats")
        self.say(theirs, self.mate, "Secret play")
        rows = self.rows()
        self.assertEqual([row["team"] for row in rows], [mine])
        self.assertIsNone(rows[0]["message"])
        self.client.force_login(self.user)
        response = self.client.get(self.home_url)
        self.assertNotContains(response, "Secret play")
        self.assertNotContains(response, reverse("chat:thread", args=[theirs.pk]))

    def test_reported_message_still_previewed(self):
        team = make_team(self.user)
        message = self.say(team, self.user, "Reported text")
        message.is_flagged = True
        message.save(update_fields=["is_flagged"])
        self.assertEqual(self.rows()[0]["preview"], "alex: Reported text")

    def test_two_queries_for_many_teams(self):
        for index in range(3):
            team = make_team(self.mate, name=f"Team {index}")
            add_player(team, self.user)
            self.say(team, self.mate, f"Message {index}")
        with self.assertNumQueries(2):
            self.assertEqual(len(self.rows()), 3)

    def test_anonymous_renders_nothing(self):
        html = Template("{% load chat_tags %}{% home_chat_panel %}").render(Context({}))
        self.assertEqual(html.strip(), "")
