"""Display names for conversations. Never an email address."""

from core.names import FALLBACK_NAME, display_name

__all__ = ["FALLBACK_NAME", "conversation_label", "display_name"]


def conversation_label(conversation, viewer, members=None):
    """What the inbox calls one conversation for one viewer.

    ``members`` is an optional preload of the conversation's other active
    members, oldest first-name order, so list pages stay at a fixed query
    count. Without it, one query loads them.
    """
    from .models import Conversation

    if conversation.kind == Conversation.Kind.TEAM:
        return conversation.team.name
    if members is None:
        memberships = conversation.memberships.select_related("user").all()
        members = [
            membership.user
            for membership in memberships
            if membership.left_at is None
            and (viewer is None or membership.user_id != viewer.pk)
        ]
        members.sort(
            key=lambda user: (user.first_name or "", user.last_name or "", user.pk or 0)
        )
    if conversation.kind == Conversation.Kind.DIRECT:
        if not members:
            return FALLBACK_NAME
        return display_name(members[0])
    title = (conversation.title or "").strip()
    if title:
        return title
    label = ", ".join(display_name(user) for user in members[:3])
    if len(members) > 3:
        label += f" +{len(members) - 3}"
    return label
