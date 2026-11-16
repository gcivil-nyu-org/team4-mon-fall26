from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import inbox
from .factories import add_player, make_direct, make_team, make_user
from .factories import post_message
from .models import ConversationRead, Message


def thread_url(conversation):
    return reverse("chat:conversation", args=[conversation.pk])


class InboxTests(TestCase):
    def setUp(self):
        self.user = make_user("alex", first_name="Alex")
        self.mate = make_user("mate", first_name="Sam")
        self.team = make_team(self.user)
        add_player(self.team, self.mate)

    def test_inbox_lists_chats_and_shows_pick_prompt(self):
        post_message(self.team.conversation, self.mate, body="Hello team")
        self.client.force_login(self.user)
        response = self.client.get(reverse("chat:inbox"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Violets")
        self.assertContains(response, "Pick a chat or start one.")

    def test_inbox_empty_state(self):
        loner = make_user("loner")
        self.client.force_login(loner)
        response = self.client.get(reverse("chat:inbox"))
        self.assertContains(response, "No chats yet")
        self.assertContains(response, f'href="{reverse("chat:new")}"')

    def test_conversation_marks_selected_row(self):
        direct = make_direct(self.user, self.mate)
        self.client.force_login(self.user)
        response = self.client.get(thread_url(self.team.conversation))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, thread_url(direct))
        self.assertContains(response, 'aria-current="page"', count=1)

    def test_conversation_hides_list_on_phone_and_has_back_link(self):
        self.client.force_login(self.user)
        response = self.client.get(thread_url(self.team.conversation))
        self.assertContains(response, "pn-chat-list d-none d-lg-block")
        self.assertContains(response, "All chats")

    def test_inbox_hides_thread_on_phone(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("chat:inbox"))
        self.assertContains(response, "pn-chat-thread d-none d-lg-block")

    def test_post_redirects_to_latest(self):
        self.client.force_login(self.mate)
        url = thread_url(self.team.conversation)
        response = self.client.post(url, {"body": "hi"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(f"{url}#latest"))
        self.assertEqual(Message.objects.get().body, "hi")

    def test_non_member_gets_404_on_get_post_and_flag(self):
        outsider = make_user("outsider")
        message = post_message(self.team.conversation, self.mate, body="hi")
        self.client.force_login(outsider)
        url = thread_url(self.team.conversation)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"body": "hi"}).status_code, 404)
        self.assertEqual(
            self.client.post(
                reverse("chat:flag", args=[self.team.conversation.pk, message.pk])
            ).status_code,
            404,
        )
        self.assertEqual(Message.objects.count(), 1)
        message.refresh_from_db()
        self.assertFalse(message.is_flagged)

    def test_cannot_report_own_message(self):
        self.client.force_login(self.mate)
        message = post_message(self.team.conversation, self.mate, body="mine")
        response = self.client.post(
            reverse("chat:flag", args=[self.team.conversation.pk, message.pk])
        )
        self.assertRedirects(
            response,
            thread_url(self.team.conversation),
            fetch_redirect_response=False,
        )
        message.refresh_from_db()
        self.assertFalse(message.is_flagged)

    def test_any_member_can_report(self):
        self.client.force_login(self.user)
        message = post_message(self.team.conversation, self.mate, body="flag me")
        self.assertRedirects(
            self.client.post(
                reverse("chat:flag", args=[self.team.conversation.pk, message.pk])
            ),
            thread_url(self.team.conversation),
            fetch_redirect_response=False,
        )
        message.refresh_from_db()
        self.assertTrue(message.is_flagged)

    def test_shows_latest_50_and_older_link(self):
        for index in range(55):
            post_message(self.team.conversation, self.mate, body=f"message {index}")
        self.client.force_login(self.user)
        response = self.client.get(thread_url(self.team.conversation))
        self.assertEqual(len(response.context["chat_messages"]), 50)
        self.assertContains(response, "Older messages")
        self.assertContains(response, "message 54")
        self.assertNotContains(response, "message 4\n")

    def test_before_param_pages_back(self):
        for index in range(10):
            post_message(self.team.conversation, self.mate, body=f"message {index}")
        pks = list(
            Message.objects.filter(conversation=self.team.conversation)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        self.client.force_login(self.user)
        response = self.client.get(
            thread_url(self.team.conversation), {"before": pks[5]}
        )
        self.assertEqual(response.status_code, 200)
        shown = [message.body for message in response.context["chat_messages"]]
        self.assertEqual(shown, [f"message {index}" for index in range(5)])

    def test_bad_before_value_shows_latest(self):
        other = make_direct(self.user, self.mate)
        other_message = post_message(other, self.mate, body="elsewhere")
        for index in range(55):
            post_message(self.team.conversation, self.mate, body=f"message {index}")
        self.client.force_login(self.user)
        url = thread_url(self.team.conversation)
        for value in ["abc", other_message.pk]:
            response = self.client.get(url, {"before": value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context["chat_messages"]), 50)

    def test_old_team_url_redirects_member(self):
        self.client.force_login(self.mate)
        self.assertRedirects(
            self.client.get(reverse("chat:thread", args=[self.team.pk])),
            thread_url(self.team.conversation),
        )

    def test_old_team_url_404_for_outsider(self):
        self.client.force_login(make_user("outsider"))
        self.assertEqual(
            self.client.get(reverse("chat:thread", args=[self.team.pk])).status_code,
            404,
        )

    def test_page_has_one_primary_button(self):
        self.client.force_login(self.user)
        response = self.client.get(thread_url(self.team.conversation))
        self.assertEqual(response.content.decode().count('btn btn-primary"'), 1)

    def test_opening_conversation_clears_count(self):
        post_message(self.team.conversation, self.mate, body="hello")
        self.assertEqual(inbox.unread_total(self.user), 1)
        self.client.force_login(self.user)
        self.client.get(thread_url(self.team.conversation))
        self.assertEqual(inbox.unread_total(self.user), 0)

    def test_get_creates_marker(self):
        before = timezone.now()
        self.client.force_login(self.user)
        self.client.get(thread_url(self.team.conversation))
        marker = ConversationRead.objects.get()
        self.assertEqual(
            (marker.user, marker.conversation), (self.user, self.team.conversation)
        )
        self.assertGreaterEqual(marker.last_read_at, before)


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
