from django import template
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.utils.timesince import timesince

from chat.models import Message
from teams.models import Team

register = template.Library()

PREVIEW_LENGTH = 60


def _preview(message):
    """'First name: first 60 characters…' for one message."""
    author = message.author
    name = author.first_name or author.email.split("@")[0] or author.username
    body = " ".join(message.body.split())
    if len(body) > PREVIEW_LENGTH:
        body = body[:PREVIEW_LENGTH].rstrip() + "…"
    return f"{name}: {body}"


def _relative_time(moment):
    """'5 minutes ago', with one unit only."""
    if (timezone.now() - moment).total_seconds() < 60:
        return "Just now"
    return f"{timesince(moment, depth=1)} ago"


def home_chat_rows(user):
    """One row per team the user is on, each with its latest message.

    Two queries for any number of teams:
    1. The user's teams, each annotated with the pk of its latest message.
    2. Those messages, with their authors.

    Teams come from the user's roster only, so a message from a different
    team cannot appear. Reported messages stay in the preview, because the
    thread page shows them too (with a "Reported" badge).
    """
    latest_pk = (
        Message.objects.filter(team=OuterRef("pk"))
        .order_by("-created_at", "-pk")
        .values("pk")[:1]
    )
    teams = list(
        Team.objects.filter(roster__player=user)
        .select_related("sport")
        .annotate(latest_message_pk=Subquery(latest_pk))
        .order_by("-roster__joined_at")
    )
    message_pks = [team.latest_message_pk for team in teams if team.latest_message_pk]
    latest = (
        Message.objects.select_related("author").in_bulk(message_pks)
        if message_pks
        else {}
    )
    rows = []
    for team in teams:
        message = latest.get(team.latest_message_pk)
        rows.append(
            {
                "team": team,
                "message": message,
                "preview": _preview(message) if message else "",
                "time_label": _relative_time(message.created_at) if message else "",
                # Unread badge (later PR): add "unread_count" here with one
                # grouped query, then show it in _home_panel.html.
            }
        )
    return rows


@register.inclusion_tag("chat/_home_panel.html", takes_context=True)
def home_chat_panel(context):
    """The "Team chat" card on the dashboard rail."""
    user = context.get("user")
    if not getattr(user, "is_authenticated", False):
        return {"show_panel": False}
    return {"show_panel": True, "rows": home_chat_rows(user)}
