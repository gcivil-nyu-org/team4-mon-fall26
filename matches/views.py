from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.roles import SCOREKEEPER_ROLE, has_role, users_with_role
from teams.models import Season
from teams.season_rules import SeasonAction
from teams.views import _require_league_admin

from .forms import MatchForm, ScoreForm
from .models import Match
from .scorekeeping import group_assigned_matches
from .schedule import schedule_matches, seasons_visible_to
from .standings import compute_standings


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
        "season", "home_team", "away_team", "facility", "scorekeeper"
    )
    season_id = request.GET.get("season", "")
    if season_id.isdecimal():
        season = get_object_or_404(Season, pk=season_id)
        matches = matches.filter(season=season)
    return render(
        request,
        "matches/manage_matches.html",
        {
            "matches": matches,
            "scorekeeper_ids": set(
                users_with_role(SCOREKEEPER_ROLE).values_list("pk", flat=True)
            ),
            "seasons": seasons,
            "season": season,
            "can_schedule": _schedulable_seasons().exists(),
            "season_is_schedulable": season is not None
            and season.allows(SeasonAction.SCHEDULE_MATCH),
            "nav_section": "league_setup",
        },
    )


@login_required
def my_matches(request):
    """The matches assigned to the signed-in scorekeeper."""
    if not has_role(request.user, SCOREKEEPER_ROLE):
        raise PermissionDenied("Scorekeeper access is required.")
    return render(
        request,
        "matches/my_matches.html",
        {"groups": group_assigned_matches(request.user), "nav_section": "my_matches"},
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
            if season_id.isdecimal()
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
    elif not match.can_change:
        messages.error(request, f"{match.season} isn't open or active.")
    else:
        match.cancel()
        messages.success(request, f"Cancelled {match}.")
    return redirect(_manage_url(match.season_id))


def _score_match(request, match, form, back_url, nav_section):
    """Shared save path for League Admin and scorekeeper score entry."""
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved the score for {match}.")
        return redirect(back_url)
    return render(
        request,
        "matches/score_form.html",
        {
            "form": form,
            "match": match,
            "back_url": back_url,
            "nav_section": nav_section,
        },
    )


@login_required
def record_score(request, pk):
    """League Admins enter or correct a match score. Corrections overwrite."""
    _require_league_admin(request.user)
    match = get_object_or_404(
        Match.objects.select_related(
            "season", "home_team__sport", "away_team__sport", "facility"
        ),
        pk=pk,
    )
    if not match.can_change:
        if match.is_cancelled:
            messages.error(request, "Cancelled matches can't be scored.")
        else:
            messages.error(request, f"{match.season} isn't open or active.")
        return redirect(_manage_url(match.season_id))
    form = ScoreForm(request.POST or None, instance=match)
    return _score_match(
        request, match, form, _manage_url(match.season_id), "league_setup"
    )


@login_required
def submit_score(request, pk):
    """The assigned scorekeeper submits the result for their match."""
    if not has_role(request.user, SCOREKEEPER_ROLE):
        raise PermissionDenied("Scorekeeper access is required.")
    match = get_object_or_404(
        Match.objects.select_related(
            "season", "home_team__sport", "away_team__sport", "facility"
        ),
        pk=pk,
    )
    if match.scorekeeper_id != request.user.pk:
        raise PermissionDenied("Only the assigned scorekeeper can submit this score.")
    if not match.can_change:
        if match.is_cancelled:
            messages.error(request, "Cancelled matches can't be scored.")
        else:
            messages.error(request, f"{match.season} isn't open or active.")
        return redirect("matches:mine")
    if not match.has_started:
        # My matches hides the button until then. A typed URL gets the same answer.
        messages.error(request, "You can submit the score once the match starts.")
        return redirect("matches:mine")
    form = ScoreForm(request.POST or None, instance=match)
    return _score_match(request, match, form, reverse("matches:mine"), "my_matches")


@login_required
def schedule_seasons(request):
    """Every season the player can see, linking to its schedule."""
    seasons = seasons_visible_to(request.user).order_by("-start_date", "name")
    return render(
        request,
        "matches/schedule_seasons.html",
        {"seasons": seasons, "nav_section": "schedule"},
    )


@login_required
def season_schedule(request, pk):
    """All of a season's matches by time, optionally for one division."""
    season = get_object_or_404(seasons_visible_to(request.user), pk=pk)
    divisions = season.divisions.all()
    matches = schedule_matches().filter(season=season)
    division_id = request.GET.get("division", "")
    # A value that isn't one of this season's divisions just shows every match.
    division = (
        divisions.filter(pk=division_id).first() if division_id.isdecimal() else None
    )
    if division:
        # Matches have no division of their own, so it comes from their teams.
        # A match between two divisions is on both divisions' schedules.
        matches = matches.filter(
            Q(home_team__division=division) | Q(away_team__division=division)
        )
    return render(
        request,
        "matches/season_schedule.html",
        {
            "season": season,
            "divisions": divisions,
            "division": division,
            "matches": matches,
            "nav_section": "schedule",
        },
    )


@login_required
def standings_seasons(request):
    """Every season the player can see, linking to its standings."""
    seasons = seasons_visible_to(request.user).order_by("-start_date", "name")
    season_id = request.GET.get("season", "")
    if season_id.isdecimal() and seasons.filter(pk=season_id).exists():
        return redirect("matches:season_standings", pk=season_id)
    return render(
        request,
        "matches/standings_seasons.html",
        {"seasons": seasons, "nav_section": "schedule"},
    )


@login_required
def season_standings(request, pk):
    """The season's leaderboard, optionally for one division."""
    season = get_object_or_404(seasons_visible_to(request.user), pk=pk)
    seasons = seasons_visible_to(request.user).order_by("-start_date", "name")
    divisions = season.divisions.all()
    division_id = request.GET.get("division", "")
    # A value that isn't one of this season's divisions just shows every team.
    division = (
        divisions.filter(pk=division_id).first() if division_id.isdecimal() else None
    )
    return render(
        request,
        "matches/season_standings.html",
        {
            "season": season,
            "seasons": seasons,
            "divisions": divisions,
            "division": division,
            "rows": compute_standings(season, division),
            "nav_section": "schedule",
        },
    )
