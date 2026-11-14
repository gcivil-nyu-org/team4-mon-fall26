"""What the moderation queue lists, shared with the League Admin overview."""

from forums.selectors import flagged_replies, flagged_topics

from .models import Message


def flagged_messages():
    """Reported team chat messages for the moderation queue."""
    return Message.objects.filter(is_flagged=True).select_related("team", "author")


def flagged_content():
    """The moderation queue's rows, keyed by the name its template uses."""
    return {
        "flagged": flagged_messages(),
        "flagged_topics": flagged_topics(),
        "flagged_replies": flagged_replies(),
    }


def flagged_total():
    """How many rows the moderation queue lists. One COUNT per section."""
    return sum(rows.count() for rows in flagged_content().values())
