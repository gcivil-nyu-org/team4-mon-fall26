from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from matches.schedule import player_schedule
from matches.standings import dashboard_standings, team_records, total_record
from teams.models import Roster

from .overview import overview_context

# The teammates card shows this many faces, then "+N".
TEAMMATE_PREVIEW_LIMIT = 5


def home(request):
    """Landing page for visitors, dashboard for signed-in players."""
    if not request.user.is_authenticated:
        return render(request, "core/home.html")
    return render(request, "core/dashboard.html", _dashboard_context(request.user))


def _dashboard_context(user):
    entries = list(
        Roster.objects.filter(player=user)
        .select_related("team__sport", "team__season")
        .order_by("-joined_at")
    )
    team_ids = [entry.team_id for entry in entries]
    records = team_records(team_ids)
    for entry in entries:
        entry.record = records[entry.team_id]

    upcoming, past = player_schedule(user)
    to_play = [match for match in upcoming if not match.is_cancelled]
    teammates = (
        get_user_model()
        .objects.filter(roster_entries__team_id__in=team_ids)
        .exclude(pk=user.pk)
        .distinct()
    )
    teammate_count = teammates.count()
    extra_teammate_count = teammate_count - TEAMMATE_PREVIEW_LIMIT
    if extra_teammate_count < 0:
        extra_teammate_count = 0
    standings_label, standings_tabs = dashboard_standings(user, timezone.localdate())
    return {
        "entries": entries,
        "record": total_record(records),
        "next_match": to_play[0] if to_play else None,
        "to_play_count": len(to_play),
        "upcoming_matches": upcoming,
        "past_matches": past,
        "teammate_count": teammate_count,
        "teammates": teammates[:TEAMMATE_PREVIEW_LIMIT],
        "extra_teammate_count": extra_teammate_count,
        "standings_label": standings_label,
        "standings_tabs": standings_tabs,
    }


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


def csrf_failure(request, reason=""):
    """CSRF_FAILURE_VIEW (#271): a stale form, often a second login submit.

    A signed-in user who resubmits the login form goes to Home, because the
    login already worked. Every other failure gets a friendly 403 page
    instead of Django's raw one.
    """
    if request.user.is_authenticated and request.path == reverse("login"):
        messages.info(request, "You're already logged in.")
        return redirect("core:home")
    return render(request, "core/csrf_failure.html", status=403)
