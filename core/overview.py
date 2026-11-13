"""Queries for the League Admin overview page."""

from django.db.models import Count
from django.urls import reverse

from audit.models import AuditLog
from chat.models import Message
from facilities.models import Facility
from matches.schedule import schedule_matches
from teams.models import FreeAgentRequest, Season, Team
from teams.season_rules import SeasonAction, SeasonState

LIST_LIMIT = 10
UPCOMING_LIMIT = 5
RECENT_CHANGES_LIMIT = 8


def needs_score_matches(now):
    """Ended, uncancelled matches with no result in live seasons, oldest first."""
    return schedule_matches().needing_score(now).order_by("ends_at", "pk")


def upcoming_matches(now):
    """Scheduled matches that haven't started, in seasons that allow scheduling."""
    return (
        schedule_matches()
        .scheduled()
        .filter(
            starts_at__gte=now,
            season__in=Season.objects.allowing(SeasonAction.SCHEDULE_MATCH),
        )
        .order_by("starts_at", "pk")
    )


def pending_request_count():
    """Free agent requests the placement page can still match."""
    return FreeAgentRequest.objects.filter(
        season__in=Season.objects.allowing(SeasonAction.MATCH_FREE_AGENTS)
    ).count()


def flagged_message_count():
    """The same messages the moderation queue lists."""
    return Message.objects.filter(is_flagged=True).count()


def season_state_counts():
    """One {label, count} per season state, in lifecycle order."""
    found = dict(
        Season.objects.order_by().values_list("state").annotate(total=Count("pk"))
    )
    return [
        {"label": SeasonState(value).label, "count": found.get(value, 0)}
        for value in SeasonState.values
    ]


def current_seasons():
    """Every season except closed ones, newest first."""
    return Season.objects.exclude(state=SeasonState.CLOSED).order_by(
        "-start_date", "name"
    )


def recent_changes():
    """The latest audit log rows, newest first."""
    return AuditLog.objects.select_related("actor")[:RECENT_CHANGES_LIMIT]


def overview_context(now):
    """Everything core/overview.html shows."""
    needs_score = needs_score_matches(now)
    upcoming = upcoming_matches(now)
    return {
        "counts": {
            "pending_requests": pending_request_count(),
            "needs_score": needs_score.count(),
            "flagged": flagged_message_count(),
            "upcoming_matches": upcoming.count(),
            "teams": Team.objects.count(),
            "active_facilities": Facility.objects.filter(is_active=True).count(),
        },
        "needs_score_rows": [
            {"match": match, "score_url": reverse("matches:score", args=[match.pk])}
            for match in needs_score[:LIST_LIMIT]
        ],
        "upcoming_matches": upcoming[:UPCOMING_LIMIT],
        "season_counts": season_state_counts(),
        "seasons": current_seasons(),
        "recent_changes": recent_changes(),
    }
