"""A user with no name shows as "PlayNYU player", never as their email (#248)."""

import datetime

from django.contrib.auth import get_user_model
from django.core import mail
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.placeholders import send_invite_email
from accounts.roles import LEAGUE_ADMIN_ROLE, SCOREKEEPER_ROLE, assign_role
from audit.models import AuditLog
from chat.factories import make_team, post_message
from chat.names import display_name as chat_display_name
from core.names import FALLBACK_NAME, display_name
from facilities.models import Facility
from forums.models import Reply, Topic
from matches.forms import MatchForm
from matches.models import Match
from notifications.models import Notification
from teams.models import FreeAgentRequest, Roster, Season, Sport, Team
from teams.season_rules import SeasonState

NAMELESS_EMAIL = "nameless@nyu.edu"


def make_user(email, first_name="", last_name="", role=None):
    # Real accounts use the email as the username (accounts/forms.py).
    user = get_user_model().objects.create_user(
        username=email,
        email=email,
        password="pass12345!",
        first_name=first_name,
        last_name=last_name,
    )
    if role:
        assign_role(user, role)
    return user


class DisplayNameTests(TestCase):
    def test_full_name(self):
        user = make_user("ana@nyu.edu", "Ana", "Diaz")
        self.assertEqual(display_name(user), "Ana Diaz")

    def test_first_name_only(self):
        self.assertEqual(display_name(make_user("ana@nyu.edu", "Ana")), "Ana")

    def test_no_name_falls_back(self):
        user = make_user(NAMELESS_EMAIL)
        self.assertEqual(FALLBACK_NAME, "PlayNYU player")
        self.assertEqual(display_name(user), FALLBACK_NAME)

    def test_blank_name_falls_back(self):
        self.assertEqual(
            display_name(make_user(NAMELESS_EMAIL, " ", " ")), FALLBACK_NAME
        )

    def test_none_falls_back(self):
        self.assertEqual(display_name(None), FALLBACK_NAME)

    def test_chat_names_use_the_same_helper(self):
        self.assertIs(chat_display_name, display_name)

    def test_template_filter(self):
        rendered = Template("{% load ui %}{{ person|display_name }}").render(
            Context({"person": make_user(NAMELESS_EMAIL)})
        )
        self.assertEqual(rendered, FALLBACK_NAME)


class NamelessPageTests(TestCase):
    """Each page shows the fallback name and never the nameless user's email."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("boss@nyu.edu", "Lee", "Admin", role=LEAGUE_ADMIN_ROLE)
        cls.nameless = make_user(NAMELESS_EMAIL)
        cls.soccer = Sport.objects.create(name="Soccer")

    def assert_nameless(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, FALLBACK_NAME)
        self.assertNotContains(response, NAMELESS_EMAIL)

    def test_forum_topic_list(self):
        Topic.objects.create(author=self.nameless, title="Pickup", body="Who is in?")
        self.client.force_login(self.admin)
        self.assert_nameless(self.client.get(reverse("forums:list")))

    def test_forum_topic_detail_author(self):
        topic = Topic.objects.create(author=self.nameless, title="Pickup", body="Hi")
        self.client.force_login(self.admin)
        self.assert_nameless(self.client.get(reverse("forums:detail", args=[topic.pk])))

    def test_forum_topic_detail_reply_author(self):
        topic = Topic.objects.create(author=self.admin, title="Pickup", body="Hi")
        Reply.objects.create(topic=topic, author=self.nameless, body="I am in")
        self.client.force_login(self.admin)
        self.assert_nameless(self.client.get(reverse("forums:detail", args=[topic.pk])))

    def test_moderation_queue_topic_and_reply(self):
        topic = Topic.objects.create(
            author=self.nameless, title="Pickup", body="Hi", is_flagged=True
        )
        Reply.objects.create(
            topic=topic, author=self.nameless, body="Bad reply", is_flagged=True
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("chat:moderation_queue"))
        self.assertContains(response, "Bad reply")
        self.assert_nameless(response)

    def test_moderation_queue_message(self):
        team = make_team(self.nameless)
        post_message(team.conversation, self.nameless, body="Bad dm", is_flagged=True)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("chat:moderation_queue"))
        self.assertContains(response, "Bad dm")
        self.assert_nameless(response)

    def test_overview_recent_changes_actor(self):
        assign_role(self.nameless, LEAGUE_ADMIN_ROLE)
        AuditLog.objects.create(
            actor=self.nameless,
            action=AuditLog.Action.UPDATED,
            object_type="Season",
            object_id="1",
            object_repr="Fall",
        )
        self.client.force_login(self.admin)
        self.assert_nameless(self.client.get(reverse("core:overview")))

    def test_overview_deleted_reply_row(self):
        topic = Topic.objects.create(author=self.admin, title="Pickup", body="Hi")
        reply = Reply.objects.create(topic=topic, author=self.nameless, body="Spam")
        self.client.force_login(self.admin)
        self.client.post(reverse("forums:delete_reply", args=[topic.pk, reply.pk]))
        self.assertTrue(AuditLog.objects.filter(object_type="Reply").exists())
        self.assert_nameless(self.client.get(reverse("core:overview")))

    def make_match(self, scorekeeper):
        season = Season.objects.create(
            name="Fall",
            start_date=datetime.date(2026, 9, 1),
            state=SeasonState.ACTIVE,
        )
        home, away = (
            Team.objects.create(
                name=name, sport=self.soccer, season=season, captain=self.admin
            )
            for name in ("Violets", "Bobcats")
        )
        starts_at = timezone.now() + datetime.timedelta(days=2)
        return Match.objects.create(
            season=season,
            home_team=home,
            away_team=away,
            facility=Facility.objects.create(
                name="Pier 40", source=Facility.Source.NYU
            ),
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=2),
            scorekeeper=scorekeeper,
        )

    def test_roles_page_labels_the_email(self):
        # The roles page is the one League Admin page that shows the email (#261).
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:roles"))
        self.assertContains(response, FALLBACK_NAME)
        self.assertContains(
            response,
            f'<span class="visually-hidden">Email: </span>{NAMELESS_EMAIL}',
            count=1,
        )
        self.assertContains(response, NAMELESS_EMAIL, count=1)

    def test_manage_matches_scorekeeper(self):
        assign_role(self.nameless, SCOREKEEPER_ROLE)
        self.make_match(self.nameless)
        self.client.force_login(self.admin)
        self.assert_nameless(self.client.get(reverse("matches:manage")))

    def test_match_form_scorekeeper_choice(self):
        assign_role(self.nameless, SCOREKEEPER_ROLE)
        match = self.make_match(self.nameless)
        field = MatchForm(instance=match, season=match.season).fields["scorekeeper"]
        self.assertEqual(field.label_from_instance(self.nameless), FALLBACK_NAME)
        self.client.force_login(self.admin)
        self.assert_nameless(self.client.get(reverse("matches:edit", args=[match.pk])))

    def test_manage_free_agents(self):
        season = Season.objects.create(
            name="Fall",
            start_date=datetime.date(2026, 9, 1),
            state=SeasonState.OPEN,
        )
        FreeAgentRequest.objects.create(
            player=self.nameless, season=season, sport=self.soccer
        )
        self.client.force_login(self.admin)
        self.assert_nameless(
            self.client.get(
                reverse("teams:manage_season_free_agents", args=[season.pk])
            )
        )

    def test_free_agent_pool(self):
        season = Season.objects.create(
            name="Fall",
            start_date=datetime.date(2026, 9, 1),
            state=SeasonState.OPEN,
        )
        FreeAgentRequest.objects.create(
            player=self.nameless, season=season, sport=self.soccer
        )
        self.client.force_login(self.admin)
        self.assert_nameless(self.client.get(reverse("teams:free_agent_pool")))

    def test_profile_page(self):
        self.client.force_login(self.admin)
        self.assert_nameless(
            self.client.get(reverse("profiles:detail", args=[self.nameless.pk]))
        )


class NamelessTextTests(TestCase):
    """Strings built in Python use the same fallback."""

    @classmethod
    def setUpTestData(cls):
        cls.captain = make_user("cap@nyu.edu", "Cap", "Tain")
        cls.nameless = make_user(NAMELESS_EMAIL)

    def test_roster_notifications(self):
        team = make_team(self.captain)
        entry = Roster.objects.create(team=team, player=self.nameless)
        entry.delete()
        verbs = list(Notification.objects.values_list("verb", flat=True))
        self.assertIn(f"{FALLBACK_NAME} joined {team}", verbs)
        self.assertIn(f"{FALLBACK_NAME} left {team}", verbs)
        self.assertFalse(any(NAMELESS_EMAIL in verb for verb in verbs))

    def test_invite_email_inviter(self):
        invitee = make_user("new@nyu.edu")
        send_invite_email(
            "https://play.example.com", invitee, make_team(self.captain), self.nameless
        )
        self.assertIn(f"{FALLBACK_NAME} added you", mail.outbox[0].body)
        self.assertNotIn(NAMELESS_EMAIL, mail.outbox[0].body)

    def test_model_strings(self):
        team = make_team(self.captain)
        topic = Topic.objects.create(author=self.captain, title="Pickup", body="Hi")
        reply = Reply.objects.create(topic=topic, author=self.nameless, body="In")
        entry = Roster.objects.create(team=team, player=self.nameless)
        for obj in (reply, entry):
            with self.subTest(obj=type(obj).__name__):
                self.assertIn(FALLBACK_NAME, str(obj))
                self.assertNotIn(NAMELESS_EMAIL, str(obj))
