"""Shared test helpers for the chat inbox."""

from django.contrib.auth import get_user_model

from teams.models import Roster, Sport, Team

from .models import Conversation, ConversationMember, Message


def make_user(username, first_name="", last_name=""):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@nyu.edu",
        password="pass12345!",
        first_name=first_name,
        last_name=last_name,
    )


def make_team(captain, name="Violets"):
    sport, _ = Sport.objects.get_or_create(name="Soccer")
    team = Team.objects.create(name=name, sport=sport, captain=captain)
    Roster.objects.create(team=team, player=captain, role=Roster.Role.CAPTAIN)
    return team


def add_player(team, user):
    return Roster.objects.create(team=team, player=user, role=Roster.Role.PLAYER)


def make_direct(a, b):
    """A 1:1 conversation between two users, whoever starts it."""
    conversation, _ = Conversation.objects.get_or_create(
        kind=Conversation.Kind.DIRECT,
        direct_key=Conversation.direct_key_for(a, b),
    )
    for user in (a, b):
        ConversationMember.objects.get_or_create(conversation=conversation, user=user)
    return conversation


def make_group(creator, *others, title=""):
    conversation = Conversation.objects.create(
        kind=Conversation.Kind.GROUP, title=title
    )
    for user in (creator, *others):
        ConversationMember.objects.get_or_create(conversation=conversation, user=user)
    return conversation


def post_message(conversation, author, body="hi", **fields):
    return Message.objects.create(
        conversation=conversation, author=author, body=body, **fields
    )


__all__ = [
    "add_player",
    "make_direct",
    "make_group",
    "make_team",
    "make_user",
    "post_message",
]
