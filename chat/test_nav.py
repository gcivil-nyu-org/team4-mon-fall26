from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from notifications.models import Notification

from .factories import (
    add_player,
    make_direct,
    make_group,
    make_team,
    make_user,
    post_message,
)
from .templatetags.chat_tags import chat_nav


class ChatNavTests(TestCase):
    def setUp(self):
        self.user = make_user("alex")
        self.mate = make_user("sam", first_name="Sam")
        self.team = make_team(self.user)
        add_player(self.team, self.mate)

    def nav(self, user=None):
        return chat_nav({"user": user or self.user})

    def test_navbar_always_links_to_inbox(self):
        loner = make_user("loner")
        two_teams = make_team(self.mate, name="Bobcats")
        add_player(two_teams, self.user)
        for user in (loner, self.user):
            self.assertEqual(self.nav(user)["url"], reverse("chat:inbox"))

    def test_navbar_counts_direct_and_group_unread(self):
        direct = make_direct(self.user, self.mate)
        group = make_group(self.user, self.mate)
        post_message(self.team.conversation, self.mate, body="team")
        post_message(direct, self.mate, body="direct")
        post_message(group, self.mate, body="group")
        self.assertEqual(self.nav()["unread"], 3)

    def test_navbar_uses_one_query(self):
        for index in range(3):
            team = make_team(self.mate, name=f"Team {index}")
            add_player(team, self.user)
            post_message(team.conversation, self.mate, body=f"Message {index}")
        with self.assertNumQueries(1):
            self.assertEqual(self.nav()["unread"], 3)

    def test_navbar_aria_label(self):
        direct = make_direct(self.user, self.mate)
        group = make_group(self.user, self.mate)
        post_message(self.team.conversation, self.mate, body="team")
        post_message(direct, self.mate, body="direct")
        post_message(group, self.mate, body="group")
        self.client.force_login(self.user)
        response = self.client.get(reverse("teams:list"))
        self.assertContains(response, 'aria-label="Chat, 3 unread"')
        self.assertContains(
            response, '<span class="badge bg-red-lt ms-1 pn-num">3</span>', html=True
        )

    def test_navbar_has_no_count_when_all_read(self):
        Notification.objects.all().delete()
        self.client.force_login(self.user)
        response = self.client.get(reverse("teams:list"))
        self.assertContains(response, 'aria-label="Chat"')
        self.assertNotContains(response, "unread")

    def test_navbar_skips_query_for_anonymous(self):
        with self.assertNumQueries(0):
            self.assertEqual(chat_nav({}), {"unread": 0, "url": ""})
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, 'aria-label="Chat')

    def test_chat_message_creates_no_notification(self):
        Notification.objects.all().delete()
        self.client.force_login(self.user)
        self.client.post(
            reverse("chat:conversation", args=[self.team.conversation.pk]),
            {"body": "Practice at 6"},
        )
        from .models import Message

        self.assertEqual(Message.objects.count(), 1)
        self.assertFalse(Notification.objects.exists())


class HomeChatPanelTests(TestCase):
    def setUp(self):
        self.user = make_user("alex")
        self.mate = make_user("sam", first_name="Sam")
        self.team = make_team(self.user)
        add_player(self.team, self.mate)
        self.home_url = reverse("core:home")

    def test_home_card_shows_five_rows_and_all_chats_link(self):
        for index in range(6):
            make_direct(self.user, make_user(f"friend{index}", first_name=f"F{index}"))
        self.client.force_login(self.user)
        response = self.client.get(self.home_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "chat/_home_panel.html")
        self.assertContains(response, "All chats")
        self.assertContains(response, f'href="{reverse("chat:inbox")}"')
        # Five conversation rows; the dashboard's team card links the old
        # thread URL, which looks different.
        import re

        row_links = re.findall(r'href="/chat/\d+/"', response.content.decode())
        self.assertEqual(len(row_links), 5)

    def test_home_card_rows_link_to_conversation(self):
        direct = make_direct(self.user, self.mate)
        group = make_group(self.user, self.mate, title="Pickup crew")
        post_message(group, self.mate, body="See you there")
        self.client.force_login(self.user)
        response = self.client.get(self.home_url)
        self.assertContains(
            response, f'href="{reverse("chat:conversation", args=[direct.pk])}"'
        )
        self.assertContains(
            response, f'href="{reverse("chat:conversation", args=[group.pk])}"'
        )
        self.assertContains(response, "Pickup crew")
        response = self.client.get(reverse("chat:conversation", args=[group.pk]))
        self.assertContains(response, "See you there")

    def test_home_card_empty_state(self):
        loner = make_user("loner")
        self.client.force_login(loner)
        response = self.client.get(self.home_url)
        self.assertContains(response, "Join a team or start a chat.")

    def test_anonymous_renders_nothing(self):
        html = Template("{% load chat_tags %}{% home_chat_panel %}").render(Context({}))
        self.assertEqual(html.strip(), "")
