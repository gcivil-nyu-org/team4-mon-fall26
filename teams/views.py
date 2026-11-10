from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from facilities.models import Facility
from matches.models import Match
from matches.schedule import seasons_visible_to, team_schedule

from .forms import (
    AddPlayerForm,
    DivisionCreateForm,
    EventTypeForm,
    FreeAgentRequestForm,
    SeasonForm,
    SportForm,
    TeamCreateForm,
)
from .models import (
    Division,
    EventType,
    FreeAgentRequest,
    Roster,
    Season,
    Sport,
    Team,
    season_team_for,
)
from .season_rules import (
    ALLOWED_TRANSITIONS,
    SeasonAction,
    SeasonState,
    division_matches,
)

# Button labels for each allowed state change on the League Admin seasons page.
TRANSITION_LABELS = {
    (SeasonState.DRAFT, SeasonState.OPEN): "Open registration",
    (SeasonState.OPEN, SeasonState.DRAFT): "Move back to draft",
    (SeasonState.OPEN, SeasonState.ACTIVE): "Start season",
    (SeasonState.ACTIVE, SeasonState.CLOSED): "Close season",
}


@login_required
def team_list(request):
    teams = Team.objects.filter(roster__player=request.user).select_related(
        "season", "division"
    )
    return render(request, "teams/team_list.html", {"teams": teams})


@login_required
def create_team(request):
    form = TeamCreateForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        team = None
        with transaction.atomic():
            season = form.cleaned_data["season"]
            if season is not None:
                season = Season.objects.select_for_update().get(pk=season.pk)
                current = season_team_for(request.user, season)
                if not season.allows(SeasonAction.CREATE_TEAM):
                    form.add_error(
                        "season", "That season isn't accepting new teams right now."
                    )
                elif current is not None:
                    form.add_error(
                        "season",
                        "You're already on a team this season. Players can be on "
                        "one team per season.",
                    )
                elif season.max_roster_size < 1:
                    form.add_error(
                        "season",
                        "That season's rosters are full, so it can't take a new team.",
                    )

            if not form.errors:
                team = form.save(commit=False)
                selected_sport = form.cleaned_data["sport"]
                team.sport = selected_sport
                team.season = season
                team.captain = request.user
                team.save()
                Roster.objects.create(
                    team=team, player=request.user, role=Roster.Role.CAPTAIN
                )
        if team is not None:
            messages.success(request, f"Team {team.name} created. You are the captain.")
            return redirect("teams:detail", pk=team.pk)
    return render(
        request,
        "teams/team_form.html",
        {
            "form": form,
            "has_sports": form.fields["sport"].queryset.exists(),
            "has_open_seasons": form.fields["season"].queryset.exists(),
            "is_league_admin": request.user.is_superuser
            or has_role(request.user, LEAGUE_ADMIN_ROLE),
        },
    )


@login_required
def team_detail(request, pk):
    team = get_object_or_404(
        Team.objects.select_related("captain", "season", "division"), pk=pk
    )
    # Rosters show members' emails, so only teammates can see them.
    if not team.roster.filter(player=request.user).exists():
        raise Http404
    # Captain first, then players in the order they joined.
    roster = team.roster.select_related("player").order_by("role", "joined_at")
    upcoming_matches, past_matches = team_schedule(team, request.user)
    return render(
        request,
        "teams/team_detail.html",
        {
            "team": team,
            "roster": roster,
            "is_captain": team.captain_id == request.user.pk,
            "is_full": len(roster) >= team.max_roster_size,
            "can_add": team.allows(SeasonAction.ADD_PLAYER),
            "can_remove": team.allows(SeasonAction.REMOVE_PLAYER),
            "can_leave": team.allows(SeasonAction.LEAVE_TEAM),
            "upcoming_matches": upcoming_matches,
            "past_matches": past_matches,
            "can_view_schedule": seasons_visible_to(request.user)
            .filter(pk=team.season_id)
            .exists(),
        },
    )


@login_required
def add_player(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if team.captain_id != request.user.pk:
        raise PermissionDenied("Only the captain can add players.")
    if not team.allows(SeasonAction.ADD_PLAYER):
        messages.error(request, "This season isn't accepting new players.")
        return redirect("teams:detail", pk=team.pk)
    if request.method == "GET" and team.is_full():
        messages.info(request, f"The roster is full ({team.max_roster_size} players).")
        return redirect("teams:detail", pk=team.pk)

    form = AddPlayerForm(request.POST or None, team=team)
    if request.method == "POST":
        with transaction.atomic():
            season = None
            if team.season_id:
                season = Season.objects.select_for_update().get(pk=team.season_id)
            # Lock the team so two adds can't both pass the roster-size check.
            Team.objects.select_for_update().get(pk=team.pk)
            added = form.is_valid()
            if added and season and not season.allows(SeasonAction.ADD_PLAYER):
                form.add_error(None, "This season isn't accepting new players.")
                added = False
            if added:
                # TODO: players are added without consent; replace with an invite/accept flow later.
                if team.season_id:
                    FreeAgentRequest.objects.filter(
                        player=form.player, season_id=team.season_id
                    ).delete()
                Roster.objects.create(
                    team=team, player=form.player, role=Roster.Role.PLAYER
                )
        if added:
            messages.success(request, f"Added {form.player.email} to {team.name}.")
            return redirect("teams:detail", pk=team.pk)
    return render(request, "teams/add_player.html", {"form": form, "team": team})


@login_required
@require_POST
def remove_player(request, pk, entry_pk):
    team = get_object_or_404(Team, pk=pk)
    if team.captain_id != request.user.pk:
        raise PermissionDenied("Only the captain can remove players.")
    if not team.allows(SeasonAction.REMOVE_PLAYER):
        messages.error(
            request,
            "Rosters are locked once the season starts, so players can't be removed.",
        )
        return redirect("teams:detail", pk=team.pk)
    entry = get_object_or_404(
        team.roster.select_related("player"), pk=entry_pk, role=Roster.Role.PLAYER
    )
    entry.delete()
    messages.success(request, f"Removed {entry.player.email} from {team.name}.")
    return redirect("teams:detail", pk=team.pk)


@login_required
@require_POST
def leave_team(request, pk):
    team = get_object_or_404(Team, pk=pk)
    entry = get_object_or_404(team.roster, player=request.user)
    # Nobody else can manage the team yet, so the captain has to stay.
    if entry.role == Roster.Role.CAPTAIN:
        messages.error(request, "Captains can't leave their own team.")
        return redirect("teams:detail", pk=team.pk)
    if not team.allows(SeasonAction.LEAVE_TEAM):
        messages.error(
            request,
            "Rosters are locked once the season starts, so you can't leave this team.",
        )
        return redirect("teams:detail", pk=team.pk)
    entry.delete()
    messages.success(request, f"You left {team.name}.")
    return redirect("teams:list")


@login_required
def free_agent_pool(request):
    current_requests = (
        FreeAgentRequest.objects.filter(player=request.user)
        .select_related("season", "division")
        .order_by("season__start_date", "season__name")
    )
    form = FreeAgentRequestForm(request.POST or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        selected_season = form.cleaned_data["season"]
        created = False
        with transaction.atomic():
            try:
                season = (
                    Season.objects.allowing(SeasonAction.REQUEST_FREE_AGENT)
                    .select_for_update()
                    .get(pk=selected_season.pk)
                )
            except Season.DoesNotExist:
                form.add_error("season", "That season is no longer accepting requests.")
            else:
                if season_team_for(request.user, season) is not None:
                    form.add_error("season", "You already have a team in this season.")
                else:
                    _, created = FreeAgentRequest.objects.get_or_create(
                        player=request.user,
                        season=season,
                        defaults={
                            "sport": form.cleaned_data["sport"],
                            "division": form.cleaned_data["division"],
                        },
                    )

        if created:
            messages.success(
                request, f"You're now in the {season.name} free agent pool."
            )
            return redirect("teams:free_agent_pool")
        if not form.errors:
            messages.info(request, "You already requested placement this season.")
            return redirect("teams:free_agent_pool")

    return render(
        request,
        "teams/free_agent_pool.html",
        {
            "form": form,
            "requests": current_requests,
            "has_available_seasons": form.fields["season"].queryset.exists(),
        },
    )


@login_required
@require_POST
def cancel_free_agent_request(request, pk):
    season_id = (
        FreeAgentRequest.objects.filter(pk=pk, player=request.user)
        .values_list("season_id", flat=True)
        .first()
    )
    if season_id is None:
        raise Http404

    with transaction.atomic():
        season = Season.objects.select_for_update().get(pk=season_id)
        if not season.allows(SeasonAction.REQUEST_FREE_AGENT):
            messages.error(
                request, f"{season.name} is closed, so requests can't be changed."
            )
            return redirect("teams:free_agent_pool")
        request_to_cancel = FreeAgentRequest.objects.filter(
            pk=pk, player=request.user
        ).first()
        if request_to_cancel is not None:
            request_to_cancel.delete()
            messages.success(request, "Your free agent request was cancelled.")
        else:
            messages.info(request, "That request has already been processed.")
    return redirect("teams:free_agent_pool")


def _require_league_admin(user):
    if not (user.is_superuser or has_role(user, LEAGUE_ADMIN_ROLE)):
        raise PermissionDenied("League Admin access is required.")


@login_required
def manage_free_agents(request):
    _require_league_admin(request.user)
    seasons = Season.objects.allowing(SeasonAction.MATCH_FREE_AGENTS).annotate(
        request_count=Count("free_agent_requests")
    )
    return render(request, "teams/manage_free_agents.html", {"seasons": seasons})


@login_required
def league_setup(request):
    """League Admin hub linking to every E2 configuration page."""
    _require_league_admin(request.user)
    counts = {
        "seasons": Season.objects.count(),
        "sports": Sport.objects.count(),
        "event_types": EventType.objects.count(),
        "divisions": Division.objects.count(),
        "waiting_requests": FreeAgentRequest.objects.filter(
            season__in=Season.objects.allowing(SeasonAction.MATCH_FREE_AGENTS)
        ).count(),
        "upcoming_matches": Match.objects.scheduled()
        .filter(
            starts_at__gte=timezone.now(),
            season__in=Season.objects.allowing(SeasonAction.SCHEDULE_MATCH),
        )
        .count(),
        "facilities": Facility.objects.count(),
    }
    return render(
        request,
        "teams/league_setup.html",
        {"counts": counts, "nav_section": "league_setup"},
    )


@login_required
def manage_divisions(request):
    _require_league_admin(request.user)
    seasons = Season.objects.order_by("-start_date", "name")
    return render(
        request,
        "teams/manage_divisions.html",
        {"seasons": seasons, "nav_section": "league_setup"},
    )


@login_required
def manage_season_free_agents(request, season_pk):
    _require_league_admin(request.user)
    season = get_object_or_404(
        Season.objects.allowing(SeasonAction.MATCH_FREE_AGENTS), pk=season_pk
    )
    free_agents = (
        FreeAgentRequest.objects.filter(season=season)
        .select_related("player", "division")
        .order_by("requested_at", "pk")
    )
    teams = list(
        Team.objects.filter(season=season)
        .annotate(roster_count=Count("roster"))
        .select_related("division")
        .order_by("pk")
    )
    available_spots = sum(
        max(0, team.max_roster_size - team.roster_count) for team in teams
    )
    return render(
        request,
        "teams/manage_free_agents.html",
        {
            "season": season,
            "free_agents": free_agents,
            "teams": teams,
            "available_spots": available_spots,
        },
    )


@login_required
def manage_season_divisions(request, season_pk):
    _require_league_admin(request.user)
    season = get_object_or_404(Season, pk=season_pk)
    form = DivisionCreateForm(request.POST or None, season=season)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                division = form.save()
        except IntegrityError:
            form.add_error(
                "name", "A division with this name already exists in this season."
            )
        else:
            messages.success(request, f"Added {division.name} to {season.name}.")
            return redirect("teams:manage_season_divisions", season_pk=season.pk)
    divisions = Division.objects.filter(season=season).order_by("name", "pk")
    return render(
        request,
        "teams/manage_divisions.html",
        {
            "season": season,
            "form": form,
            "divisions": divisions,
            "nav_section": "league_setup",
        },
    )


@login_required
@require_POST
def match_free_agents(request, season_pk):
    _require_league_admin(request.user)
    matched = 0
    stale = 0

    with transaction.atomic():
        season = get_object_or_404(
            Season.objects.allowing(SeasonAction.MATCH_FREE_AGENTS).select_for_update(),
            pk=season_pk,
        )
        free_agents = list(
            FreeAgentRequest.objects.filter(season=season)
            .select_for_update()
            .select_related("player", "division")
            .order_by("requested_at", "pk")
        )
        teams = list(
            Team.objects.filter(season=season)
            .select_for_update()
            .select_related("season", "division")
            .order_by("pk")
        )
        roster_counts = {team.pk: team.roster.count() for team in teams}

        for free_agent in free_agents:
            if season_team_for(free_agent.player, season) is not None:
                free_agent.delete()
                stale += 1
                continue

            available = [
                team
                for team in teams
                if team.sport_id == free_agent.sport_id
                and division_matches(team.division_id, free_agent.division_id)
                and roster_counts[team.pk] < team.max_roster_size
            ]
            if not available:
                continue

            team = min(
                available,
                key=lambda candidate: (roster_counts[candidate.pk], candidate.pk),
            )
            Roster.objects.create(
                team=team,
                player=free_agent.player,
                role=Roster.Role.PLAYER,
            )
            free_agent.delete()
            roster_counts[team.pk] += 1
            matched += 1

        remaining = len(free_agents) - matched - stale

    if remaining:
        messages.info(
            request,
            f"Placed {matched} player(s). {remaining} remain in the pool because "
            "no eligible team with an open spot matched their sport and division.",
        )
    else:
        messages.success(request, f"Placed {matched} player(s) in {season.name}.")
    return redirect("teams:manage_season_free_agents", season_pk=season.pk)


@login_required
def manage_sports(request):
    """Display and manage sports for League Admins."""
    _require_league_admin(request.user)

    form = SportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Sport added successfully.")
        return redirect("teams:manage_sports")

    sports = Sport.objects.annotate(event_type_count=Count("event_types")).order_by(
        "name"
    )

    return render(
        request,
        "teams/manage_sports.html",
        {"form": form, "sports": sports, "nav_section": "league_setup"},
    )


@login_required
def manage_event_types(request):
    """Display and manage event types for League Admins."""
    _require_league_admin(request.user)

    form = EventTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Event type added successfully.")
        return redirect("teams:manage_event_types")

    event_types = EventType.objects.select_related("sport").order_by(
        "sport__name", "name"
    )

    return render(
        request,
        "teams/manage_event_types.html",
        {
            "form": form,
            "has_sports": Sport.objects.exists(),
            "event_types": event_types,
            "nav_section": "league_setup",
        },
    )


def _season_transitions(season):
    return [
        {"state": target, "label": TRANSITION_LABELS[(season.state, target)]}
        for target in SeasonState.values
        if target in ALLOWED_TRANSITIONS.get(season.state, ())
    ]


@login_required
def manage_seasons(request):
    _require_league_admin(request.user)
    seasons = Season.objects.annotate(team_count=Count("teams")).order_by(
        "-start_date", "name"
    )
    rows = [
        {"season": season, "transitions": _season_transitions(season)}
        for season in seasons
    ]
    return render(
        request, "teams/manage_seasons.html", {"rows": rows, "nav_section": "seasons"}
    )


@login_required
def season_form(request, pk=None):
    _require_league_admin(request.user)
    season = get_object_or_404(Season, pk=pk) if pk else None
    if season and season.state == SeasonState.CLOSED:
        messages.error(request, f"{season.name} is closed and can't be edited.")
        return redirect("teams:manage_seasons")
    form = SeasonForm(request.POST or None, instance=season)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        if season:
            messages.success(request, f"Saved {saved.name}.")
        else:
            messages.success(
                request,
                f"Created {saved.name} as a draft. Players see it once you open registration.",
            )
        return redirect("teams:manage_seasons")
    return render(
        request,
        "teams/season_form.html",
        {"form": form, "season": season, "nav_section": "seasons"},
    )


@login_required
@require_POST
def change_season_state(request, pk):
    _require_league_admin(request.user)
    target = request.POST.get("state", "")
    with transaction.atomic():
        season = get_object_or_404(Season.objects.select_for_update(), pk=pk)
        try:
            season.move_to(target)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(
                request, f"{season.name} is now {season.get_state_display().lower()}."
            )
    return redirect("teams:manage_seasons")
