"""What the moderation queue lists, shared with the League Admin overview."""

from forums.selectors import flagged_replies, flagged_topics
from matches.models import MatchComment

from .models import Conversation, Message
from .names import conversation_label


def flagged_messages():
    """Reported chat messages for the moderation queue."""
    return (
        Message.objects.filter(is_flagged=True)
        .select_related("conversation__team", "author")
        .prefetch_related("conversation__memberships__user")
    )


def flagged_comments():
    """Reported match comments for the moderation queue, newest first."""
    return (
        MatchComment.objects.filter(is_flagged=True)
        .select_related("author", "match__home_team", "match__away_team")
        .order_by("-created_at", "-pk")
    )


def flagged_content():
    """The moderation queue's rows, keyed by the name its template uses."""
    return {
        "flagged": flagged_messages(),
        "flagged_topics": flagged_topics(),
        "flagged_replies": flagged_replies(),
        "flagged_comments": flagged_comments(),
    }


def flagged_total():
    """How many rows the moderation queue lists. One COUNT per section."""
    return sum(rows.count() for rows in flagged_content().values())


def queue_label(conversation):
    """What the moderation queue calls one conversation."""
    if conversation.kind == Conversation.Kind.TEAM:
        return conversation.team.name
    if conversation.kind == Conversation.Kind.DIRECT:
        return "Direct message"
    return f"Group: {conversation_label(conversation, None)}"
