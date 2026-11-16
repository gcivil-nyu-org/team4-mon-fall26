from django.test import TestCase
from django.urls import reverse

from accounts.models import PendingAccount

from .factories import make_direct, make_group, make_team, make_user
from .models import Block, Message


class BlockTests(TestCase):
    def setUp(self):
        self.user = make_user("alex", first_name="Alex")
        self.mate = make_user("mate", first_name="Sam")
        self.team = make_team(self.user)
        self.direct = make_direct(self.user, self.mate)

    def block_url(self):
        return reverse("chat:block", args=[self.mate.pk])

    def conversation_url(self):
        return reverse("chat:conversation", args=[self.direct.pk])

    def test_block_disables_composer_with_neutral_text(self):
        self.client.force_login(self.user)
        self.client.post(self.block_url(), {"action": "block", "next": self.direct.pk})
        response = self.client.get(self.conversation_url())
        self.assertContains(response, "You can't message this person.")
        self.assertNotContains(response, "blocked you")

    def test_blocked_user_post_refused(self):
        self.client.force_login(self.user)
        self.client.post(self.block_url(), {"action": "block"})
        self.client.force_login(self.mate)
        response = self.client.post(self.conversation_url(), {"body": "hi"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Message.objects.exists())

    def test_unblock_restores_posting(self):
        self.client.force_login(self.user)
        self.client.post(self.block_url(), {"action": "block"})
        self.client.post(self.block_url(), {"action": "unblock"})
        response = self.client.post(self.conversation_url(), {"body": "back"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Message.objects.get().body, "back")

    def test_block_twice_is_one_row(self):
        self.client.force_login(self.user)
        self.client.post(self.block_url(), {"action": "block"})
        self.client.post(self.block_url(), {"action": "block"})
        self.assertEqual(
            Block.objects.filter(blocker=self.user, blocked=self.mate).count(), 1
        )

    def test_block_self_does_nothing(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("chat:block", args=[self.user.pk]), {"action": "block"}
        )
        self.assertRedirects(
            response, reverse("chat:inbox"), fetch_redirect_response=False
        )
        self.assertFalse(Block.objects.exists())

    def test_block_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.block_url()).status_code, 405)

    def test_block_menu_only_in_direct(self):
        self.client.force_login(self.user)
        response = self.client.get(self.conversation_url())
        self.assertContains(response, "Block Sam")
        response = self.client.get(
            reverse("chat:conversation", args=[self.team.conversation.pk])
        )
        self.assertNotContains(response, "Block ")
        group = make_group(self.user, self.mate)
        response = self.client.get(reverse("chat:conversation", args=[group.pk]))
        self.assertContains(response, "Leave chat")
        self.assertNotContains(response, "Block ")

    def test_leave_group_removes_access(self):
        group = make_group(self.user, self.mate)
        self.client.force_login(self.user)
        self.client.post(reverse("chat:leave", args=[group.pk]))
        self.assertEqual(
            self.client.get(reverse("chat:conversation", args=[group.pk])).status_code,
            404,
        )

    def test_leave_refused_for_team_and_direct(self):
        self.client.force_login(self.user)
        for conversation in (self.team.conversation, self.direct):
            self.assertEqual(
                self.client.post(
                    reverse("chat:leave", args=[conversation.pk])
                ).status_code,
                404,
            )

    def test_deleted_partner_disables_composer(self):
        self.mate.delete()
        self.client.force_login(self.user)
        response = self.client.get(self.conversation_url())
        self.assertContains(response, "You can't message this person.")


class BlockConfirmEscapeTests(TestCase):
    """The block and unblock confirm() text holds a user-chosen name."""

    def setUp(self):
        self.user = make_user("alex", first_name="Alex")
        self.attacker = make_user(
            "mallory", first_name="x');alert(1);('", last_name="Evil"
        )
        self.direct = make_direct(self.user, self.attacker)
        self.url = reverse("chat:conversation", args=[self.direct.pk])

    def assert_name_escaped_for_js(self, response):
        body = response.content.decode()
        # HTML escaping alone is not enough: the browser decodes &#x27; back
        # to a quote before the onsubmit handler runs.
        for verb in ("Block", "Unblock"):
            self.assertNotIn(f"confirm('{verb} x&#x27;", body)
        self.assertIn("x\\u0027)\\u003Balert(1)\\u003B(\\u0027", body)

    def test_block_confirm_escapes_name(self):
        self.client.force_login(self.user)
        self.assert_name_escaped_for_js(self.client.get(self.url))

    def test_unblock_confirm_escapes_name(self):
        Block.objects.create(blocker=self.user, blocked=self.attacker)
        self.client.force_login(self.user)
        self.assert_name_escaped_for_js(self.client.get(self.url))


class BlockTargetPrivacyTests(TestCase):
    """chat:block must not tell a caller whether an account exists."""

    NEUTRAL = "You can't block or unblock this person."

    def setUp(self):
        self.user = make_user("alex", first_name="Alex")
        self.mate = make_user("mate", first_name="Sam")
        self.client.force_login(self.user)

    def post_block(self, pk, action="block"):
        return self.client.post(
            reverse("chat:block", args=[pk]), {"action": action}, follow=True
        )

    def messages_of(self, response):
        return [str(m) for m in response.context["messages"]]

    def assert_neutral(self, pk):
        for action in ("block", "unblock"):
            response = self.post_block(pk, action)
            self.assertRedirects(response, reverse("chat:inbox"))
            self.assertEqual(self.messages_of(response), [self.NEUTRAL])
        self.assertFalse(Block.objects.exists())

    def test_missing_pk_gets_neutral_redirect(self):
        self.assert_neutral(999999)

    def test_inactive_user_gets_neutral_redirect(self):
        self.mate.is_active = False
        self.mate.save()
        self.assert_neutral(self.mate.pk)

    def test_placeholder_user_gets_neutral_redirect(self):
        PendingAccount.objects.create(user=self.mate, invited_by=self.user)
        self.assert_neutral(self.mate.pk)

    def test_self_gets_neutral_redirect(self):
        self.assert_neutral(self.user.pk)

    def test_real_user_block_still_works(self):
        response = self.post_block(self.mate.pk)
        self.assertRedirects(response, reverse("chat:inbox"))
        self.assertEqual(self.messages_of(response), ["Blocked."])
        self.assertTrue(
            Block.objects.filter(blocker=self.user, blocked=self.mate).exists()
        )

    def test_can_block_and_unblock_someone_who_blocked_you(self):
        Block.objects.create(blocker=self.mate, blocked=self.user)
        self.post_block(self.mate.pk)
        self.assertTrue(
            Block.objects.filter(blocker=self.user, blocked=self.mate).exists()
        )
        self.post_block(self.mate.pk, "unblock")
        self.assertFalse(
            Block.objects.filter(blocker=self.user, blocked=self.mate).exists()
        )
