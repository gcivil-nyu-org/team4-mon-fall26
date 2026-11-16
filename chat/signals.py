"""Keep a team chat next to every team."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from teams.models import Team

from .models import Conversation


@receiver(post_save, sender=Team, dispatch_uid="chat.make_team_conversation")
def make_team_conversation(sender, instance, created, **kwargs):
    if created:
        Conversation.for_team(instance)
