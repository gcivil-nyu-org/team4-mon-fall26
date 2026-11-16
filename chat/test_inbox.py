from django.test import TestCase
from django.utils import timezone

from . import inbox
from .factories import add_player, make_direct, make_group, make_team, make_user
from .factories import post_message
from .models import Block
from .names import FALLBACK_NAME, conversation_label, display_name


class DisplayNameTests(TestCase):
    def test_display_name_falls_back(self):
        self.assertEqual(display_name(make_user("x")), "PlayNYU player")
        self.assertEqual(display_name(None), "PlayNYU player")

    def test_display_name_never_uses_email(self):
        u = make_user("sam")
        self.assertNotIn("@", display_name(u))

    def test_display_name_prefers_full_name(self):
        u = make_user("sam", first_name="Sam", last_name="Lee")
        self.assertEqual(display_name(u), "Sam Lee")


class ConversationLabelTests(TestCase):
    def test_group_label_lists_three_then_plus(self):
        creator = make_user("creator")
        others = [make_user(f"u{name}", first_name=name) for name in "ABCD"]
        group = make_group(creator, *others)
        self.assertEqual(conversation_label(group, creator), "A, B, C +1")

    def test_group_label_uses_title(self):
        creator = make_user("creator")
        group = make_group(creator, make_user("mate"), title="Pickup crew")
        self.assertEqual(conversation_label(group, creator), "Pickup crew")

    def test_direct_label_uses_other_name(self):
        a = make_user("a", first_name="Amy")
        b = make_user("b", first_name="Bo")
        direct = make_direct(a, b)
        self.assertEqual(conversation_label(direct, a), "Bo")
        self.assertEqual(conversation_label(direct, b), "Amy")


class ConversationsForTests(TestCase):
    def setUp(self):
        self.user = make_user("alex")
        self.mate = make_user("mate")
        self.team = make_team(self.user)
        add_player(self.team, self.mate)

    def test_lists_team_direct_and_group(self):
        direct = make_direct(self.user, self.mate)
        group = make_group(self.user, self.mate)
        pks = {c.pk for c in inbox.conversations_for(self.user)}
        self.assertEqual(pks, {self.team.conversation.pk, direct.pk, group.pk})

    def test_sorted_by_latest_message(self):
        older = make_direct(self.user, self.mate)
        newer_group = make_group(self.user, self.mate)
        post_message(newer_group, self.mate, body="new")
        post_message(older, self.mate, body="older but later")
        self.assertEqual(list(inbox.conversations_for(self.user))[0].pk, older.pk)

    def test_empty_chat_sorts_by_created_at(self):
        first = make_direct(self.user, self.mate)
        second = make_direct(self.user, make_user("zed"))
        pks = [c.pk for c in inbox.conversations_for(self.user)]
        self.assertLess(pks.index(second.pk), pks.index(first.pk))

    def test_no_duplicate_rows_for_two_memberships(self):
        group = make_group(self.user, self.mate)
        rows = list(inbox.conversations_for(self.user))
        self.assertEqual(len(rows), len({c.pk for c in rows}))
        self.assertIn(group.pk, {c.pk for c in rows})

    def test_outsider_cannot_view_direct(self):
        self.assertFalse(
            inbox.can_view(make_user("c"), make_direct(self.user, self.mate))
        )

    def test_left_group_member_cannot_view_and_has_no_unread(self):
        group = make_group(self.user, self.mate)
        membership = group.memberships.get(user=self.user)
        membership.left_at = timezone.now()
        membership.save(update_fields=["left_at"])
        post_message(group, self.mate, body="after you left")
        self.assertFalse(inbox.can_view(self.user, group))
        self.assertEqual(inbox.unread_total(self.user), 0)

    def test_former_team_player_has_no_unread(self):
        post_message(self.team.conversation, self.mate, body="after you left")
        self.team.roster.filter(player=self.user).delete()
        self.assertFalse(inbox.can_view(self.user, self.team.conversation))
        self.assertEqual(inbox.unread_total(self.user), 0)

    def test_own_messages_never_count(self):
        post_message(self.team.conversation, self.user, body="mine")
        self.assertEqual(inbox.unread_total(self.user), 0)

    def test_marker_clears_count(self):
        post_message(self.team.conversation, self.mate, body="hello")
        self.assertEqual(inbox.unread_total(self.user), 1)
        inbox.mark_read(self.user, self.team.conversation)
        self.assertEqual(inbox.unread_total(self.user), 0)

    def test_block_stops_posting_both_ways(self):
        Block.objects.create(blocker=self.user, blocked=self.mate)
        direct = make_direct(self.user, self.mate)
        self.assertFalse(inbox.can_post(self.user, direct))
        self.assertFalse(inbox.can_post(self.mate, direct))

    def test_deleted_partner_label_and_no_posting(self):
        direct = make_direct(self.user, self.mate)
        # A deleted account keeps no roster rows; dropping it first also
        # sidesteps a notifications receiver that would otherwise address
        # the deleted user (that app's scope, reported separately).
        self.team.roster.filter(player=self.mate).delete()
        self.mate.delete()
        direct = inbox.get_conversation_for(self.user, direct.pk)
        self.assertEqual(conversation_label(direct, self.user), FALLBACK_NAME)
        self.assertFalse(inbox.can_post(self.user, direct))

    def test_inbox_rows_query_count_is_fixed(self):
        inbox.inbox_rows(self.user)
        for index in range(9):
            post_message(make_group(self.user, self.mate), self.mate, body=f"{index}")
        with self.assertNumQueries(3):
            rows = inbox.inbox_rows(self.user)
        self.assertEqual(len(rows), 10)
