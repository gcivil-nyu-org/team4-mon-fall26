"""What players can see of the league's matches on the schedule pages.

Cancelled matches stay in on purpose: the pages mark them instead of hiding them.
"""

from django.db.models import Q
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from teams.models import Roster, Season

from .models import Match


def seasons_visible_to(user):
    """League Admins set up draft seasons, so only they can see them."""
    if user.is_superuser or has_role(user, LEAGUE_ADMIN_ROLE):
        return Season.objects.all()
    return Season.objects.visible_to_players()


def schedule_matches():
    """Matches with everything the match row partial shows."""
    return Match.objects.select_related(
        "facility", "home_team__sport", "away_team__sport"
    )


def team_schedule(team, user):
    """The team's (upcoming, past) matches, each with the nearest match first.

    A match stays upcoming until it ends, so one being played isn't past yet.
    """
    return _split(
        schedule_matches().filter(
            Q(home_team=team) | Q(away_team=team),
            season__in=seasons_visible_to(user),
        )
    )


def player_schedule(user):
    """The (upcoming, past) matches of every team the player is on.

    Split and ordered like team_schedule. Each match gets `opponent`: the
    team the player isn't on, or the away team when the player is on both.
    """
    team_ids = set(Roster.objects.filter(player=user).values_list("team_id", flat=True))
    if not team_ids:
        return [], []
    upcoming, past = _split(
        schedule_matches().filter(
            Q(home_team__in=team_ids) | Q(away_team__in=team_ids),
            season__in=seasons_visible_to(user),
        )
    )
    for match in upcoming + past:
        match.opponent = (
            match.home_team if match.home_team_id not in team_ids else match.away_team
        )
    return upcoming, past


def _split(matches):
    """(upcoming, past) from matches in start order; past is most recent first."""
    now = timezone.now()
    upcoming = [match for match in matches if match.ends_at >= now]
    past = [match for match in matches if match.ends_at < now]
    past.reverse()
    return upcoming, past
