from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role

from .factories import make_direct, make_group, make_team, make_user, post_message
from .models import Message


class ModerationQueueTests(TestCase):
    def setUp(self):
        self.admin = make_user("leagueadmin")
        assign_role(self.admin, LEAGUE_ADMIN_ROLE)
        self.captain = make_user("cap")
        self.team = make_team(self.captain)
        self.flagged = post_message(
            self.team.conversation, self.captain, body="Flagged post", is_flagged=True
        )
        self.clean = post_message(
            self.team.conversation, self.captain, body="Fine post"
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


class ModerationLabelTests(TestCase):
    def setUp(self):
        self.admin = make_user("leagueadmin")
        assign_role(self.admin, LEAGUE_ADMIN_ROLE)
        self.captain = make_user("cap", first_name="Cap")
        self.queue_url = reverse("chat:moderation_queue")

    def test_reported_direct_message_in_queue_with_label(self):
        friend = make_user("bea", first_name="Bea")
        direct = make_direct(self.captain, friend)
        post_message(direct, friend, body="Reported dm", is_flagged=True)
        self.client.force_login(self.admin)
        response = self.client.get(self.queue_url)
        self.assertContains(response, "Direct message")
        self.assertContains(response, "Reported dm")

    def test_reported_group_message_label(self):
        group = make_group(self.captain, make_user("bea"), title="Pickup crew")
        post_message(group, self.captain, body="Reported group", is_flagged=True)
        self.client.force_login(self.admin)
        response = self.client.get(self.queue_url)
        self.assertContains(response, "Group: Pickup crew")

    def test_admin_delete_direct_message(self):
        friend = make_user("bea", first_name="Bea")
        direct = make_direct(self.captain, friend)
        flagged = post_message(direct, friend, body="Bad dm", is_flagged=True)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("chat:moderate", args=[flagged.pk]),
            {"action": "delete"},
            follow=True,
        )
        self.assertContains(response, "Message deleted from Direct message.")
        self.assertFalse(Message.objects.filter(pk=flagged.pk).exists())

    def test_admin_cannot_open_unreported_direct_chat(self):
        friend = make_user("bea")
        direct = make_direct(self.captain, friend)
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("chat:conversation", args=[direct.pk])).status_code,
            404,
        )

    def test_queue_shows_no_email(self):
        friend = make_user("bea", first_name="Bea")
        direct = make_direct(self.captain, friend)
        post_message(direct, friend, body="Reported dm", is_flagged=True)
        self.client.force_login(self.admin)
        response = self.client.get(self.queue_url)
        self.assertNotContains(response, "bea@nyu.edu")
        self.assertContains(response, "Bea")
