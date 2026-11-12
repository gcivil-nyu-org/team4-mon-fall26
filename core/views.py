from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from facilities.models import Facility
from matches.models import Match
from matches.schedule import schedule_matches
from teams.models import FreeAgentRequest, Roster, Season, Team
from teams.season_rules import SeasonAction, SeasonState


def home(request):
    """Landing page for visitors, dashboard for signed-in players."""
    if not request.user.is_authenticated:
        return render(request, "core/home.html")
    entries = (
        Roster.objects.filter(player=request.user)
        .select_related("team", "team__season")
        .order_by("-joined_at")
    )
    team_ids = [entry.team_id for entry in entries]
    teammates = (
        get_user_model()
        .objects.filter(roster_entries__team_id__in=team_ids)
        .exclude(pk=request.user.pk)
        .distinct()
    )
    return render(
        request,
        "core/dashboard.html",
        {
            "entries": entries,
            "team_count": len(team_ids),
            "captain_count": sum(e.role == Roster.Role.CAPTAIN for e in entries),
            "teammate_count": teammates.count(),
            "teammates": teammates[:5],
        },
    )


def health(request):
    """Plain-text health check, handy for load balancers and smoke tests."""
    return HttpResponse("ok", content_type="text/plain")


def _require_league_admin(user):
    """Same gate as teams.views: League Admins and superusers only."""
    if not (user.is_superuser or has_role(user, LEAGUE_ADMIN_ROLE)):
        raise PermissionDenied("League Admin access is required.")


@login_required
def overview(request):
    """League Admin overview: league-wide counts and quick links."""
    _require_league_admin(request.user)
    schedulable = Season.objects.allowing(SeasonAction.SCHEDULE_MATCH)
    upcoming_matches = (
        schedule_matches()
        .scheduled()
        .filter(starts_at__gte=timezone.now(), season__in=schedulable)
        .order_by("starts_at", "pk")[:5]
    )
    season_counts = [
        {
            "label": SeasonState(value).label,
            "count": Season.objects.filter(state=value).count(),
        }
        for value in SeasonState.values
    ]
    counts = {
        "teams": Team.objects.count(),
        "pending_requests": FreeAgentRequest.objects.filter(
            season__in=Season.objects.allowing(SeasonAction.MATCH_FREE_AGENTS)
        ).count(),
        "upcoming_matches": (
            Match.objects.scheduled()
            .filter(starts_at__gte=timezone.now(), season__in=schedulable)
            .count()
        ),
        "active_facilities": Facility.objects.filter(is_active=True).count(),
    }
    seasons = Season.objects.order_by("-start_date", "name")
    return render(
        request,
        "core/overview.html",
        {
            "season_counts": season_counts,
            "counts": counts,
            "seasons": seasons,
            "upcoming_matches": upcoming_matches,
            "nav_section": "overview",
        },
    )
