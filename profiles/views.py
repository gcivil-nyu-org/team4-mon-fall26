from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.templatetags.ui import ordinal
from matches.schedule import seasons_visible_to
from matches.standings import standings_by_team, team_records
from matches.stats import player_recent_lines, player_season_stats
from teams.season_rules import SeasonState

from .forms import ProfileForm
from .models import PlayerProfile


def _profile_url(user):
    return reverse("profiles:detail", args=[user.pk])


def _team_result(standing, record):
    """Table line for one roster row. A dash means there is no record yet."""
    if standing:
        row = standing["row"]
        return (
            f"{ordinal(standing['position'])} · "
            f"{row['won']}–{row['drawn']}–{row['lost']}"
        )
    if record and record["played"]:
        return f"{record['won']}–{record['drawn']}–{record['lost']}"
    return "–"


@login_required
def profile_detail(request, pk):
    """Any signed in user can view a player's profile. Email is never shown;
    N number and NetID are shown only to the profile's owner."""
    player = get_object_or_404(get_user_model(), pk=pk, is_active=True)
    profile = PlayerProfile.objects.filter(user=player).first()
    visible_seasons = seasons_visible_to(request.user)
    roster = list(
        player.roster_entries.filter(
            Q(team__season__isnull=True) | Q(team__season__in=visible_seasons)
        )
        .select_related("team__sport", "team__season", "team__division")
        .order_by("-joined_at")
    )
    # A closed season, or a team with no season, has no live table.
    open_season_ids = []
    closed_team_ids = []
    for entry in roster:
        season = entry.team.season
        if season is None or season.state == SeasonState.CLOSED:
            closed_team_ids.append(entry.team_id)
        else:
            open_season_ids.append(season.pk)
    standings = standings_by_team(open_season_ids)
    records = team_records(closed_team_ids)
    teams = [
        {
            "entry": entry,
            "result": _team_result(
                standings.get(entry.team_id),
                records.get(entry.team_id),
            ),
        }
        for entry in roster
    ]
    return render(
        request,
        "profiles/profile_detail.html",
        {
            "player": player,
            "profile": profile,
            "teams": teams,
            "is_owner": player.pk == request.user.pk,
            "season_stats": player_season_stats(player, request.user),
            "recent_lines": player_recent_lines(player, request.user),
        },
    )


@login_required
def edit_profile(request, pk):
    # Loaded separately from request.user so a rejected form never touches the signed-in user object.
    user = get_object_or_404(get_user_model(), pk=pk)
    if user.pk != request.user.pk:
        raise PermissionDenied("You can only edit your own profile.")

    profile = PlayerProfile.objects.filter(user=user).first()
    if profile is None:
        return redirect("profiles:create")
    form = ProfileForm(request.POST or None, instance=profile, user=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect(_profile_url(user))
    return render(request, "profiles/edit_profile.html", {"form": form})


@login_required
def create_profile(request):
    if PlayerProfile.objects.filter(user=request.user).exists():
        messages.info(request, "You already have a profile. You can edit it here.")
        return redirect("profiles:edit", pk=request.user.pk)

    # Loaded separately from request.user so a rejected form never touches the signed-in user object.
    user = get_user_model().objects.get(pk=request.user.pk)
    form = ProfileForm(
        request.POST or None, instance=PlayerProfile(user=user), user=user
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been created.")
        return redirect(_profile_url(user))
    return render(
        request,
        "profiles/edit_profile.html",
        {
            "form": form,
            "heading": "Create profile",
            "button": "Create profile",
            "rejected": "created",
        },
    )
