"""Unread chat counts, from each player's ThreadRead markers."""

from datetime import datetime
from datetime import timezone as dt_timezone

from django.db.models import (
    Count,
    DateTimeField,
    IntegerField,
    OuterRef,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from teams.models import Team

from .models import Message, ThreadRead

# Stands in for a missing marker, so every message counts.
NEVER_READ = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)


def teams_with_unread(user):
    """The user's teams, each annotated with ``unread_count``.

    A message is unread when a different player wrote it after the user's
    marker for that team. With no marker, every message from a different
    player is unread. The count adds no query: it is a subquery.
    """
    last_read = ThreadRead.objects.filter(user=user, team=OuterRef("pk")).values(
        "last_read_at"
    )[:1]
    unread = (
        Message.objects.filter(
            team=OuterRef("pk"), created_at__gt=OuterRef("chat_last_read_at")
        )
        .exclude(author=user)
        .order_by()
        .values("team")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return Team.objects.filter(roster__player=user).annotate(
        chat_last_read_at=Coalesce(
            Subquery(last_read),
            Value(NEVER_READ),
            output_field=DateTimeField(),
        ),
        unread_count=Coalesce(Subquery(unread, output_field=IntegerField()), Value(0)),
    )


def mark_thread_read(user, team, moment=None):
    """Set the user's marker for the team's thread to ``moment`` (default now)."""
    ThreadRead.objects.update_or_create(
        user=user, team=team, defaults={"last_read_at": moment or timezone.now()}
    )
