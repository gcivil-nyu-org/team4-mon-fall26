"""Who sees which conversations, and how many messages are unread.

Every list, unread count and access rule lives here. Views and template
tags read from these helpers only, so direct, group and team chats behave
the same everywhere.
"""

import math
from datetime import datetime
from datetime import timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import (
    Count,
    DateTimeField,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.timesince import timesince

from teams.models import Roster

from .models import Block, Conversation, ConversationMember, ConversationRead, Message
from .names import conversation_label, display_name

# Stands in for a missing marker, so every message counts.
NEVER_READ = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)

PREVIEW_LENGTH = 60


def _preview(message, viewer):
    """'You: ...' for the viewer's own message, else 'Name: ...'."""
    if message.author_id == viewer.pk:
        name = "You"
    else:
        name = display_name(message.author)
    body = " ".join(message.body.split())
    if len(body) > PREVIEW_LENGTH:
        body = body[:PREVIEW_LENGTH].rstrip() + "…"
    return f"{name}: {body}"


def _relative_time(moment):
    """'5 minutes ago', with one unit only."""
    if (timezone.now() - moment).total_seconds() < 60:
        return "Just now"
    return f"{timesince(moment, depth=1)} ago"


def conversations_for(user):
    """The user's visible conversations, newest first.

    Team chats come from the roster; direct and group chats from active
    memberships. Each row carries its latest message, its latest time and
    its unread count, so listing them adds no queries per row.
    """
    if not getattr(user, "is_authenticated", False):
        return Conversation.objects.none()
    Kind = Conversation.Kind
    member = ConversationMember.objects.filter(
        conversation=OuterRef("pk"), user=user, left_at__isnull=True
    )
    roster = Roster.objects.filter(team=OuterRef("team"), player=user)
    latest = Message.objects.filter(conversation=OuterRef("pk")).order_by(
        "-created_at", "-pk"
    )
    marker = ConversationRead.objects.filter(
        conversation=OuterRef("pk"), user=user
    ).values("last_read_at")[:1]
    unread = (
        Message.objects.filter(
            conversation=OuterRef("pk"),
            created_at__gt=OuterRef("chat_last_read_at"),
        )
        .exclude(author=user)
        .order_by()
        .values("conversation")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return (
        Conversation.objects.filter(
            Q(Exists(roster), kind=Kind.TEAM) | Q(Exists(member))
        )
        .select_related("team", "team__sport")
        .annotate(
            latest_message_pk=Subquery(latest.values("pk")[:1]),
            latest_at=Subquery(
                latest.values("created_at")[:1], output_field=DateTimeField()
            ),
            chat_last_read_at=Coalesce(
                Subquery(marker),
                Value(NEVER_READ),
                output_field=DateTimeField(),
            ),
            unread_count=Coalesce(
                Subquery(unread, output_field=IntegerField()), Value(0)
            ),
        )
        .order_by(Coalesce("latest_at", "created_at").desc(), "-pk")
    )


def inbox_rows(user, limit=None):
    """One dict per visible conversation, in inbox order.

    Three queries for any number of chats: the conversations, their
    latest messages with authors, and their active members.
    """
    conversations = list(
        conversations_for(user)[:limit] if limit else conversations_for(user)
    )
    message_pks = [c.latest_message_pk for c in conversations if c.latest_message_pk]
    latest = (
        Message.objects.select_related("author").in_bulk(message_pks)
        if message_pks
        else {}
    )
    # Team rows only need the team logo, so a team-only list skips this query.
    member_convs = [c.pk for c in conversations if c.kind != Conversation.Kind.TEAM]
    memberships = (
        ConversationMember.objects.filter(
            conversation__in=member_convs, left_at__isnull=True
        )
        .select_related("user")
        .order_by("user__first_name", "user__last_name", "user__pk")
        if member_convs
        else []
    )
    others = {}
    for membership in memberships:
        if membership.user_id != user.pk:
            others.setdefault(membership.conversation_id, []).append(membership.user)
    rows = []
    for conversation in conversations:
        message = latest.get(conversation.latest_message_pk)
        other_members = others.get(conversation.pk, [])
        rows.append(
            {
                "conversation": conversation,
                "label": conversation_label(conversation, user, members=other_members),
                "message": message,
                "preview": _preview(message, user) if message else "",
                "time_label": _relative_time(message.created_at) if message else "",
                "unread_count": conversation.unread_count,
                "people": other_members[:3],
                "extra_people": max(0, len(other_members) - 3),
            }
        )
    return rows


def unread_total(user):
    """How many messages are unread across every visible conversation."""
    return conversations_for(user).aggregate(total=Sum("unread_count"))["total"] or 0


def can_view(user, conversation):
    """Whether ``user`` may open ``conversation`` at all."""
    if not getattr(user, "is_authenticated", False):
        return False
    if conversation.kind == Conversation.Kind.TEAM:
        if conversation.team_id is None:
            return False
        return Roster.objects.filter(team_id=conversation.team_id, player=user).exists()
    return ConversationMember.objects.filter(
        conversation=conversation, user=user, left_at__isnull=True
    ).exists()


def get_conversation_for(user, pk):
    """The conversation, or 404 when the user cannot see it."""
    conversation = get_object_or_404(Conversation.objects.select_related("team"), pk=pk)
    if not can_view(user, conversation):
        raise Http404
    return conversation


def is_blocked_between(a, b):
    """Whether either user blocked the other."""
    if getattr(a, "pk", None) is None or getattr(b, "pk", None) is None:
        return False
    return Block.objects.filter(
        Q(blocker=a, blocked=b) | Q(blocker=b, blocked=a)
    ).exists()


def other_member(conversation, viewer):
    """The other person in a direct chat, or ``None`` (direct only)."""
    if conversation.kind != Conversation.Kind.DIRECT:
        return None
    membership = (
        ConversationMember.objects.filter(
            conversation=conversation, left_at__isnull=True
        )
        .exclude(user=viewer)
        .select_related("user")
        .order_by("user__first_name", "user__last_name", "user__pk")
        .first()
    )
    return membership.user if membership else None


def can_post(user, conversation):
    """Whether ``user`` may write in ``conversation`` right now."""
    if not can_view(user, conversation):
        return False
    if conversation.kind != Conversation.Kind.DIRECT:
        return True
    other = other_member(conversation, user)
    if other is None or not other.is_active:
        return False
    return not is_blocked_between(user, other)


def mark_read(user, conversation, moment=None):
    """Set the user's marker for ``conversation`` to ``moment`` (default now)."""
    ConversationRead.objects.update_or_create(
        user=user,
        conversation=conversation,
        defaults={"last_read_at": moment or timezone.now()},
    )


def blockable_users(user):
    """Active people the user may block or unblock.

    Skips the user, inactive accounts and unclaimed placeholders. Blocks
    don't matter here, so a blocked person can still be unblocked.
    """
    User = get_user_model()
    return User.objects.filter(is_active=True, pending_account__isnull=True).exclude(
        pk=user.pk
    )


def reachable_users(user):
    """Active people the user may start a chat with.

    Skips the user, inactive accounts, unclaimed placeholders and anyone
    with a block in either direction.
    """
    return (
        blockable_users(user)
        .exclude(pk__in=Block.objects.filter(blocker=user).values("blocked_id"))
        .exclude(pk__in=Block.objects.filter(blocked=user).values("blocker_id"))
    )


def search_people(user, q):
    """Up to 20 reachable people matching ``q`` (needs 2+ characters).

    Matches first or last names anywhere, or a whole email exactly. A
    partial email never matches, so search can't be used to guess who has
    an account.
    """
    query = (q or "").replace("\x00", "").strip()
    if len(query) < 2:
        return []
    looks = Q(first_name__icontains=query) | Q(last_name__icontains=query)
    if "@" in query:
        looks |= Q(email__iexact=query)
    return list(
        reachable_users(user)
        .filter(looks)
        .order_by("first_name", "last_name", "pk")[:20]
    )


def open_direct(user, other):
    """The 1:1 chat for two users, whoever starts it.

    Returns ``(conversation, created)``. Retries once when two people
    start the same chat at the same moment.
    """
    Kind = Conversation.Kind
    key = Conversation.direct_key_for(user, other)
    for _ in range(2):
        try:
            with transaction.atomic():
                conversation, created = Conversation.objects.get_or_create(
                    kind=Kind.DIRECT, direct_key=key
                )
                for person in (user, other):
                    ConversationMember.objects.get_or_create(
                        conversation=conversation, user=person
                    )
                return conversation, created
        except IntegrityError:
            continue
    conversation = Conversation.objects.get(direct_key=key)
    for person in (user, other):
        ConversationMember.objects.get_or_create(conversation=conversation, user=person)
    return conversation, False


def start_group(user, others, title=""):
    """A group chat for ``user`` plus two to fifteen other people."""
    conversation = Conversation.objects.create(
        kind=Conversation.Kind.GROUP, title=title or ""
    )
    for person in (user, *others):
        ConversationMember.objects.get_or_create(conversation=conversation, user=person)
    return conversation


def consume_new_conversation(user):
    """Count one started chat against the user's hourly budget.

    Limits live in settings as ``CHAT_NEW_CONVERSATION_RATE_LIMIT_*`` and
    fall back to 20 chats an hour. ``accounts`` owns the buckets and the
    setting names, so this reuses its helpers without touching that app.
    """
    from django.conf import settings

    from accounts.rate_limits import _bucket_key, _consume, _prune_stale_buckets

    now = timezone.now()
    _prune_stale_buckets(now)
    return _consume(
        _bucket_key("chat-new-conversation", str(user.pk)),
        getattr(settings, "CHAT_NEW_CONVERSATION_RATE_LIMIT_ATTEMPTS", 20),
        getattr(settings, "CHAT_NEW_CONVERSATION_RATE_LIMIT_WINDOW_SECONDS", 3600),
        now,
    )


def retry_after_minutes(retry_after):
    """Whole minutes for a rate-limit wait, rounded up."""
    return max(1, math.ceil(retry_after / 60))
