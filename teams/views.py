from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role

from .forms import AddPlayerForm, FreeAgentRequestForm, TeamCreateForm
from .models import FreeAgentRequest, Roster, Season, Team, season_team_for


@login_required
def team_list(request):
    teams = Team.objects.filter(roster__player=request.user).select_related("season")
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
                if current is not None:
                    form.add_error(
                        "season",
                        "You're already on a team this season. Players can be on "
                        "one team per season.",
                    )

            if not form.errors:
                team = form.save(commit=False)
                team.season = season
                team.captain = request.user
                team.save()
                Roster.objects.create(
                    team=team, player=request.user, role=Roster.Role.CAPTAIN
                )
        if team is not None:
            messages.success(request, f"Team {team.name} created. You are the captain.")
            return redirect("teams:detail", pk=team.pk)
    return render(request, "teams/team_form.html", {"form": form})


@login_required
def team_detail(request, pk):
    team = get_object_or_404(Team.objects.select_related("captain", "season"), pk=pk)
    # Rosters show members' emails, so only teammates can see them.
    if not team.roster.filter(player=request.user).exists():
        raise Http404
    # Captain first, then players in the order they joined.
    roster = team.roster.select_related("player").order_by("role", "joined_at")
    return render(
        request,
        "teams/team_detail.html",
        {
            "team": team,
            "roster": roster,
            "is_captain": team.captain_id == request.user.pk,
            "is_full": len(roster) >= team.max_roster_size,
        },
    )


@login_required
def add_player(request, pk):
    team = get_object_or_404(Team, pk=pk)
    if team.captain_id != request.user.pk:
        raise PermissionDenied("Only the captain can add players.")
    if request.method == "GET" and team.is_full():
        messages.info(request, f"The roster is full ({team.max_roster_size} players).")
        return redirect("teams:detail", pk=team.pk)

    form = AddPlayerForm(request.POST or None, team=team)
    if request.method == "POST":
        with transaction.atomic():
            if team.season_id:
                Season.objects.select_for_update().get(pk=team.season_id)
            # Lock the team so two adds can't both pass the roster-size check.
            Team.objects.select_for_update().get(pk=team.pk)
            added = form.is_valid()
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
    entry.delete()
    messages.success(request, f"You left {team.name}.")
    return redirect("teams:list")


@login_required
def free_agent_pool(request):
    current_requests = (
        FreeAgentRequest.objects.filter(player=request.user)
        .select_related("season")
        .order_by("season__start_date", "season__name")
    )
    form = FreeAgentRequestForm(request.POST or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        selected_season = form.cleaned_data["season"]
        created = False
        with transaction.atomic():
            try:
                season = Season.objects.select_for_update().get(
                    pk=selected_season.pk, is_active=True
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
                        defaults={"sport": form.cleaned_data["sport"]},
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
        Season.objects.select_for_update().get(pk=season_id)
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
    seasons = Season.objects.filter(is_active=True).annotate(
        request_count=Count("free_agent_requests")
    )
    return render(request, "teams/manage_free_agents.html", {"seasons": seasons})


@login_required
def manage_season_free_agents(request, season_pk):
    _require_league_admin(request.user)
    season = get_object_or_404(Season, pk=season_pk, is_active=True)
    free_agents = (
        FreeAgentRequest.objects.filter(season=season)
        .select_related("player")
        .order_by("requested_at", "pk")
    )
    teams = list(
        Team.objects.filter(season=season)
        .annotate(roster_count=Count("roster"))
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
@require_POST
def match_free_agents(request, season_pk):
    _require_league_admin(request.user)
    matched = 0
    stale = 0

    with transaction.atomic():
        season = get_object_or_404(
            Season.objects.select_for_update(), pk=season_pk, is_active=True
        )
        free_agents = list(
            FreeAgentRequest.objects.filter(season=season)
            .select_for_update()
            .select_related("player")
            .order_by("requested_at", "pk")
        )
        teams = list(
            Team.objects.filter(season=season)
            .select_for_update()
            .select_related("season")
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
                if team.sport.casefold() == free_agent.sport.casefold()
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
            "no team for their requested sport has an open spot.",
        )
    else:
        messages.success(request, f"Placed {matched} player(s) in {season.name}.")
    return redirect("teams:manage_season_free_agents", season_pk=season.pk)
