from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from teams.models import Season
from teams.season_rules import SeasonAction
from teams.views import _require_league_admin

from .forms import MatchForm
from .models import Match


def _manage_url(season_id):
    return f"{reverse('matches:manage')}?season={season_id}"


def _schedulable_seasons():
    return Season.objects.allowing(SeasonAction.SCHEDULE_MATCH).order_by("name")


@login_required
def manage_matches(request):
    """League Admin list of matches, optionally filtered to one season."""
    _require_league_admin(request.user)
    seasons = Season.objects.visible_to_players().order_by("name")
    season = None
    matches = Match.objects.select_related(
        "season", "home_team", "away_team", "facility"
    )
    season_id = request.GET.get("season", "")
    if season_id.isdigit():
        season = get_object_or_404(Season, pk=season_id)
        matches = matches.filter(season=season)
    return render(
        request,
        "matches/manage_matches.html",
        {
            "matches": matches,
            "seasons": seasons,
            "season": season,
            "can_schedule": _schedulable_seasons().exists(),
            "nav_section": "league_setup",
        },
    )


@login_required
def match_form(request, pk=None):
    """Create a match in a chosen season, or edit an existing one."""
    _require_league_admin(request.user)
    match = (
        get_object_or_404(Match.objects.select_related("season"), pk=pk) if pk else None
    )
    if match:
        if match.is_cancelled:
            messages.error(request, "Cancelled matches can't be changed.")
            return redirect("matches:manage")
        season = match.season
    else:
        season_id = request.GET.get("season", "")
        season = (
            get_object_or_404(_schedulable_seasons(), pk=season_id)
            if season_id.isdigit()
            else None
        )
        if season is None:
            # Teams depend on the season, so pick the season first.
            return render(
                request,
                "matches/choose_season.html",
                {"seasons": _schedulable_seasons(), "nav_section": "league_setup"},
            )

    form = MatchForm(request.POST or None, instance=match, season=season)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if match is None:
            saved.created_by = request.user
        saved.save()
        verb = "Saved" if match else "Scheduled"
        messages.success(request, f"{verb} {saved}.")
        return redirect(_manage_url(season.pk))
    return render(
        request,
        "matches/match_form.html",
        {
            "form": form,
            "match": match,
            "season": season,
            "nav_section": "league_setup",
        },
    )


@login_required
@require_POST
def cancel_match(request, pk):
    _require_league_admin(request.user)
    match = get_object_or_404(Match, pk=pk)
    if match.is_cancelled:
        messages.info(request, f"{match} was already cancelled.")
    else:
        match.cancel()
        messages.success(request, f"Cancelled {match}.")
    return redirect(_manage_url(match.season_id))
