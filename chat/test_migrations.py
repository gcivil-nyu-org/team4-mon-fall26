"""Migrate team chats and read markers onto Conversation and back."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class MoveTeamChatsTests(TransactionTestCase):
    migrate_from = [("chat", "0002_threadread")]
    migrate_to = [("chat", "0005_drop_team_fields")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def build_old_rows(self, apps):
        User = apps.get_model("auth", "User")
        Team = apps.get_model("teams", "Team")
        Message = apps.get_model("chat", "Message")
        ThreadRead = apps.get_model("chat", "ThreadRead")
        # The pinned teams state can lag the table, so the Sport row comes
        # from the current model; its table is untouched by chat migrations
        # either way.
        from teams.models import Sport as CurrentSport

        sport, _ = CurrentSport.objects.get_or_create(name="Soccer")
        user = User.objects.create_user(username="cap", email="cap@nyu.edu")
        team = Team.objects.create(name="Violets", sport_id=sport.pk, captain=user)
        first = Message.objects.create(team=team, author=user, body="one")
        Message.objects.create(team=team, author=user, body="two")
        read_at = timezone.now()
        ThreadRead.objects.create(user=user, team=team, last_read_at=read_at)
        return team, first, user, read_at

    def test_forward_moves_messages_and_reads(self):
        try:
            apps = self.migrate(self.migrate_from)
            team, first, user, read_at = self.build_old_rows(apps)
            team_pk, user_pk, first_pk = team.pk, user.pk, first.pk

            new_apps = self.migrate(self.migrate_to)
            Message = new_apps.get_model("chat", "Message")
            Conversation = new_apps.get_model("chat", "Conversation")
            ConversationRead = new_apps.get_model("chat", "ConversationRead")

            conversation = Conversation.objects.get(team_id=team_pk)
            self.assertEqual(conversation.kind, "team")
            self.assertEqual(
                Message.objects.filter(conversation__team_id=team_pk).count(), 2
            )
            self.assertEqual(
                Message.objects.get(pk=first_pk).conversation_id, conversation.pk
            )
            self.assertEqual(
                ConversationRead.objects.get(user_id=user_pk).last_read_at,
                read_at,
            )
        finally:
            self.migrate(self.migrate_to)

    def test_backward_restores_team_and_thread_read(self):
        new_apps = self.migrate(self.migrate_to)
        User = new_apps.get_model("auth", "User")
        Team = new_apps.get_model("teams", "Team")
        Conversation = new_apps.get_model("chat", "Conversation")
        Message = new_apps.get_model("chat", "Message")
        ConversationRead = new_apps.get_model("chat", "ConversationRead")
        user = User.objects.create_user(username="cap", email="cap@nyu.edu")
        # The pinned teams state can lag the table (e.g. Sport gained
        # non-nullable-looking columns), so like build_old_rows the Sport row
        # comes from the current model.
        from teams.models import Sport as CurrentSport

        sport, _ = CurrentSport.objects.get_or_create(name="Soccer")
        team = Team.objects.create(name="Violets", sport_id=sport.pk, captain=user)
        conversation, _ = Conversation.objects.get_or_create(
            kind="team", team_id=team.pk
        )
        Message.objects.create(conversation=conversation, author=user, body="one")
        Message.objects.create(conversation=conversation, author=user, body="two")
        read_at = timezone.now()
        ConversationRead.objects.create(
            user=user, conversation=conversation, last_read_at=read_at
        )
        team_pk, user_pk = team.pk, user.pk

        try:
            old_apps = self.migrate(self.migrate_from)
            OldMessage = old_apps.get_model("chat", "Message")
            OldThreadRead = old_apps.get_model("chat", "ThreadRead")

            self.assertEqual(OldMessage.objects.filter(team_id=team_pk).count(), 2)
            self.assertEqual(
                OldThreadRead.objects.get(user_id=user_pk).last_read_at, read_at
            )
        finally:
            self.migrate(self.migrate_to)
