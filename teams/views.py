from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AddPlayerForm, TeamCreateForm
from .models import Roster, Team


@login_required
def team_list(request):
    teams = Team.objects.filter(roster__player=request.user).select_related("season")
    return render(request, "teams/team_list.html", {"teams": teams})


@login_required
def create_team(request):
    form = TeamCreateForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            team = form.save(commit=False)
            team.captain = request.user
            team.save()
            Roster.objects.create(
                team=team, player=request.user, role=Roster.Role.CAPTAIN
            )
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

    form = AddPlayerForm(request.POST or None, team=team)
    if request.method == "POST":
        with transaction.atomic():
            # Lock the team so two adds can't both pass the roster-size check.
            # TODO: the one-team-per-season check can still race across two teams.
            Team.objects.select_for_update().get(pk=team.pk)
            added = form.is_valid()
            if added:
                # TODO: players are added without consent; replace with an invite/accept flow later.
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
