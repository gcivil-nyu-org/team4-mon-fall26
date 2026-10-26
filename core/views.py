from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import render

from teams.models import Roster


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
