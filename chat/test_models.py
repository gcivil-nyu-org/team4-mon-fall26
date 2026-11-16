from django.db import IntegrityError, transaction
from django.test import TestCase

from .factories import make_team, make_user
from .models import Block, Conversation


class ConversationModelTests(TestCase):
    def test_new_team_gets_a_conversation(self):
        team = make_team(make_user("cap"))
        self.assertEqual(team.conversation.kind, Conversation.Kind.TEAM)

    def test_for_team_returns_the_same_row(self):
        team = make_team(make_user("cap"))
        self.assertEqual(Conversation.for_team(team).pk, team.conversation.pk)

    def test_direct_key_is_order_free(self):
        a, b = make_user("a"), make_user("b")
        self.assertEqual(
            Conversation.direct_key_for(a, b), Conversation.direct_key_for(b, a)
        )

    def test_second_direct_with_same_key_fails(self):
        a, b = make_user("a"), make_user("b")
        make_direct = Conversation.objects.create(
            kind="direct", direct_key=Conversation.direct_key_for(a, b)
        )
        self.assertTrue(make_direct.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Conversation.objects.create(
                kind="direct", direct_key=Conversation.direct_key_for(a, b)
            )

    def test_team_kind_without_team_fails(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Conversation.objects.create(kind="team")

    def test_self_block_fails(self):
        a = make_user("a")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Block.objects.create(blocker=a, blocked=a)

    def test_conversation_read_unique_per_user(self):
        from .models import ConversationRead

        team = make_team(make_user("cap"))
        conversation = team.conversation
        user = make_user("reader")
        ConversationRead.objects.create(
            user=user, conversation=conversation, last_read_at="2026-01-01T00:00:00Z"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConversationRead.objects.create(
                user=user,
                conversation=conversation,
                last_read_at="2026-01-02T00:00:00Z",
            )
