"""Move team chats and read markers onto Conversation rows."""

from django.db import migrations


def move_forward(apps, schema_editor):
    Conversation = apps.get_model("chat", "Conversation")
    ConversationRead = apps.get_model("chat", "ConversationRead")
    Message = apps.get_model("chat", "Message")
    Team = apps.get_model("teams", "Team")
    ThreadRead = apps.get_model("chat", "ThreadRead")

    for team in Team.objects.all():
        conversation, _ = Conversation.objects.get_or_create(
            kind="team", team_id=team.pk
        )
        Message.objects.filter(team_id=team.pk).update(conversation_id=conversation.pk)
    for marker in ThreadRead.objects.select_related("team"):
        conversation, _ = Conversation.objects.get_or_create(
            kind="team", team_id=marker.team_id
        )
        ConversationRead.objects.get_or_create(
            user_id=marker.user_id,
            conversation_id=conversation.pk,
            defaults={"last_read_at": marker.last_read_at},
        )


def move_backward(apps, schema_editor):
    Conversation = apps.get_model("chat", "Conversation")
    ConversationRead = apps.get_model("chat", "ConversationRead")
    Message = apps.get_model("chat", "Message")
    ThreadRead = apps.get_model("chat", "ThreadRead")

    # Direct and group messages have no team to go back to.
    Message.objects.filter(conversation__team__isnull=True).delete()
    for conversation in Conversation.objects.filter(kind="team"):
        Message.objects.filter(conversation_id=conversation.pk).update(
            team_id=conversation.team_id
        )
        for marker in ConversationRead.objects.filter(conversation_id=conversation.pk):
            ThreadRead.objects.get_or_create(
                user_id=marker.user_id,
                team_id=conversation.team_id,
                defaults={"last_read_at": marker.last_read_at},
            )
    # The restored rows no longer point at a conversation, so deleting the
    # Conversation rows cannot cascade back onto them.
    Message.objects.update(conversation=None)
    Conversation.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0003_conversations"),
    ]

    operations = [
        migrations.RunPython(move_forward, move_backward),
    ]
