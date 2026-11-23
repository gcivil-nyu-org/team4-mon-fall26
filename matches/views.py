from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from accounts.roles import (
    LEAGUE_ADMIN_ROLE,
    SCOREKEEPER_ROLE,
    has_role,
    users_with_role,
)
from facilities.maps import map_marker
from forums.views import can_moderate
from teams.event_types import scoring_event_type
from teams.models import Roster, Season
from teams.season_rules import SeasonAction, SeasonState
from teams.views import _require_league_admin

from .forms import MatchCommentForm, MatchForm, ScheduleFilterForm
from .match_context import (
    head_to_head,
    season_results,
    season_teams,
    standings_table,
    team_context,
)
from .models import Match, lock_facilities
from .scorekeeping import group_assigned_matches
from .sheet_forms import MatchSheet
from .schedule import (
    DEFAULT_SORTS,
    SCHEDULE_PER_PAGE,
    SCHEDULE_TABS,
    annotate_schedule_rows,
    schedule_matches,
    schedule_order,
    schedule_tab,
    seasons_visible_to,
)
from .standings import compute_standings
from .stats import (
    comparison_rows,
    match_event_types,
    period_rows,
    team_sheets,
    team_totals,
    top_performers,
)


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
        {
            "groups": group_assigned_matches(request.user),
            "can_see_drafts": request.user.is_superuser
            or has_role(request.user, LEAGUE_ADMIN_ROLE),
            "nav_section": "my_matches",
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

    saved = None
    with transaction.atomic():
        if request.method == "POST":
            # Two saves can't take the same venue, and a score can't land while
            # the teams change, between the checks and the save.
            lock_facilities([request.POST.get("facility", "")])
            if match:
                match = Match.objects.select_for_update().get(pk=match.pk)
        form = MatchForm(request.POST or None, instance=match, season=season)
        if request.method == "POST" and form.is_valid():
            saved = form.save(commit=False)
            if match is None:
                saved.created_by = request.user
            saved.save()
    if saved is not None:
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


def _score_match(request, match, nav_section):
    """Shared save path for League Admin and scorekeeper score entry."""
    sheet = MatchSheet(match, request.POST if request.method == "POST" else None)
    detail_url = reverse("matches:detail", args=[match.pk])
    if request.method == "POST" and sheet.is_valid() and sheet.save():
        messages.success(request, f"Saved the score for {match}.")
        return redirect(detail_url)
    return render(
        request,
        "matches/score_form.html",
        {
            "sheet": sheet,
            "form": sheet.score_form,
            "match": match,
            "back_url": detail_url,
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
    return _score_match(request, match, "league_setup")


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
    return _score_match(request, match, "my_matches")


@login_required
def match_detail(request, pk):
    """One match: score, standings movement, stats and season context.

    The query count is fixed, whatever the roster or season size.
    """
    user = request.user
    # Draft seasons are 404 for players, like the schedule and standings.
    match = get_object_or_404(
        Match.objects.filter(season__in=seasons_visible_to(user)).select_related(
            "season",
            "facility",
            "scorekeeper",
            "home_team__sport",
            "away_team__sport",
            "home_team__division",
        ),
        pk=pk,
    )
    comment_form = MatchCommentForm(request.POST or None)
    if request.method == "POST" and comment_form.is_valid():
        comment = comment_form.save(commit=False)
        comment.match = match
        comment.author = user
        comment.save()
        messages.success(request, "Comment posted.")
        return redirect(reverse("matches:detail", args=[match.pk]) + "#comments")
    sheets = team_sheets(match)
    show_stats = match.has_result and not match.is_cancelled
    # A result entered with no score sheet has no stats or appearances.
    stats_recorded = any(
        row.played or any(row.stats.values()) for sheet in sheets for row in sheet.rows
    )
    event_types = match_event_types(match) if show_stats else []
    teams = season_teams(match)
    results = season_results(match)
    totals = [team_totals(sheet, event_types) if show_stats else [] for sheet in sheets]
    tables = [
        (sheet, [(row, row.values(event_types)) for row in sheet.rows], sheet_totals)
        for sheet, sheet_totals in zip(sheets, totals)
    ]
    leaders, comparison = [], []
    if show_stats and event_types:
        # Picks from the loaded list: no query.
        scoring = scoring_event_type(match.home_team.sport_id, event_types)
        leaders = top_performers(sheets, event_types, scoring)
        if not any(t.leaders for t in leaders):
            leaders = []
        comparison = comparison_rows(event_types, totals[0], totals[1], scoring)
    if match.is_cancelled:
        status = "cancelled"
    elif match.has_result:
        status = "final"
    elif match.is_awaiting_score:
        status = "awaiting"
    else:
        status = "scheduled"
    facility = match.facility
    table = standings_table(match, teams, results)
    standings_url = reverse("matches:season_standings", args=[match.season_id])
    if table is not None and table.division is not None:
        standings_url += f"?division={table.division.pk}"
    return render(
        request,
        "matches/match_detail.html",
        {
            "match": match,
            "sheets": sheets,
            "tables": tables,
            "event_types": event_types,
            "periods": [] if match.is_cancelled else period_rows(match),
            "status": status,
            "stats_recorded": stats_recorded,
            "stats_missing": show_stats and not stats_recorded,
            "score_url": _score_url(user, match),
            "top_performers": leaders,
            "standings_table": table,
            "movement": table.movements if table is not None else None,
            "context_rows": team_context(match, teams, results),
            "h2h": head_to_head(match, results),
            "season_closed": match.season.state == SeasonState.CLOSED,
            "comparison": comparison,
            "markers": (
                [map_marker(facility)]
                if facility.is_active and facility.has_location
                else []
            ),
            "standings_url": standings_url,
            "comments": match.comments.select_related("author"),
            "comment_form": comment_form,
            "can_moderate": can_moderate(user),
            "nav_section": "schedule",
        },
    )


def _score_url(user, match):
    """The score page the viewer may use for this match, or None."""
    if (user.is_superuser or has_role(user, LEAGUE_ADMIN_ROLE)) and match.can_change:
        return reverse("matches:score", args=[match.pk])
    if (
        match.scorekeeper_id == user.pk
        and has_role(user, SCOREKEEPER_ROLE)
        and match.can_submit_score
    ):
        return reverse("matches:submit_score", args=[match.pk])
    return None


SCHEDULE_HEADERS = (
    ("date", "Date"),
    ("sport", "Sport"),
    ("home", "Home"),
    ("away", "Away"),
    ("venue", "Venue"),
)


def _query(params):
    return f"?{urlencode(params)}"


@login_required
def schedule(request):
    """Every match the viewer can see, in one filtered, sorted, paged table."""
    seasons = seasons_visible_to(request.user)
    form = ScheduleFilterForm(request.GET or None, seasons=seasons)
    values = form.values()
    tab = values.get("tab", "upcoming")
    sort = values.get("sort") or DEFAULT_SORTS[tab]
    matches = form.filter(schedule_matches().filter(season__in=seasons), request.user)
    matches = schedule_tab(matches, tab).order_by(*schedule_order(sort))
    page_obj = Paginator(matches, SCHEDULE_PER_PAGE).get_page(request.GET.get("page"))

    # Links rebuild the query from cleaned values, so bad ones aren't passed on.
    filters = [
        (name, getattr(values[name], "pk", values[name]))
        for name in ScheduleFilterForm.FILTERS
        if name in values
    ]
    with_tab = filters + [("tab", tab)]
    kept_sort = [("sort", sort)] if "sort" in values else []
    headers = []
    for key, label in SCHEDULE_HEADERS:
        direction = None
        if sort.removeprefix("-") == key:
            direction = "descending" if sort.startswith("-") else "ascending"
        target = f"-{key}" if direction == "ascending" else key
        headers.append((key, label, _query(with_tab + [("sort", target)]), direction))
    mine = "mine" in values
    mine_params = [item for item in filters if item[0] != "mine"]
    if not mine:
        mine_params.append(("mine", "1"))

    # The division select lists the chosen season's divisions only.
    season = values.get("season")
    divisions = season.divisions.order_by("name", "pk") if season else None
    if divisions is not None:
        form.fields["division"].queryset = divisions
    return render(
        request,
        "matches/schedule.html",
        {
            "form": form,
            "matches": annotate_schedule_rows(page_obj.object_list),
            "page_obj": page_obj,
            "querystring": urlencode(with_tab + kept_sort),
            "tab": tab,
            "tab_links": [
                (name, _query(filters + [("tab", name)])) for name in SCHEDULE_TABS
            ],
            "sort": sort,
            "kept_sort": bool(kept_sort),
            "headers": headers,
            "mine": mine,
            "mine_link": _query(mine_params + [("tab", tab)] + kept_sort),
            "has_filters": bool(filters),
            "clear_link": _query([("tab", tab)]),
            "show_divisions": divisions is not None and divisions.exists(),
            # Rows of the viewer's own teams get pn-row-me.
            "my_team_ids": set(
                Roster.objects.filter(player=request.user).values_list(
                    "team_id", flat=True
                )
            ),
            "nav_section": "schedule",
        },
    )


@login_required
def season_schedule(request, pk):
    """The old season page: the table, filtered to the season (and division)."""
    season = get_object_or_404(seasons_visible_to(request.user), pk=pk)
    params = [("season", season.pk)]
    division_id = request.GET.get("division", "")
    if division_id.isdecimal() and season.divisions.filter(pk=division_id).exists():
        params.append(("division", division_id))
    return redirect(reverse("matches:schedule") + _query(params))


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
