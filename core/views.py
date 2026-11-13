from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from matches.standings import dashboard_standings
from teams.models import Roster

from .overview import overview_context


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
    standings_label, standings_tabs = dashboard_standings(
        request.user, timezone.localdate()
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
            "standings_label": standings_label,
            "standings_tabs": standings_tabs,
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
    """League Admin overview: what needs attention, plus links to every admin page."""
    _require_league_admin(request.user)
    context = overview_context(timezone.now())
    context["nav_section"] = "overview"
    return render(request, "core/overview.html", context)
