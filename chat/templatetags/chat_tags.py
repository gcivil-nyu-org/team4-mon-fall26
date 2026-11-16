from django import template
from django.urls import reverse

from chat.inbox import inbox_rows, unread_total
from chat.moderation import queue_label

register = template.Library()


@register.inclusion_tag("chat/_home_panel.html", takes_context=True)
def home_chat_panel(context):
    """The "Chat" card on the dashboard rail."""
    user = context.get("user")
    if not getattr(user, "is_authenticated", False):
        return {"show_panel": False}
    return {"show_panel": True, "rows": inbox_rows(user, limit=5)}


@register.simple_tag(takes_context=True)
def chat_nav(context):
    """Total unread chat messages and the link for the navbar chat item.

    One query.
    """
    user = context.get("user")
    if not getattr(user, "is_authenticated", False):
        return {"unread": 0, "url": ""}
    return {"unread": unread_total(user), "url": reverse("chat:inbox")}


@register.filter
def chat_queue_label(conversation):
    """The moderation queue label for one conversation."""
    return queue_label(conversation)
