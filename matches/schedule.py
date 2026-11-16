"""What players can see of the league's matches on the schedule pages.

Cancelled matches stay in on purpose: the pages mark them instead of hiding them.
"""

from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from teams.models import Roster, Season
from teams.semesters import current_semester

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


FACILITY_UPCOMING_PER_PAGE = 20
FACILITY_RECENT_LIMIT = 5


def group_by_local_date(matches):
    """[(date, [matches])] in input order, by the local (New York) start date.

    `{% regroup %}` on `starts_at.date` would use the UTC date, which is wrong
    for a late-evening match.
    """
    groups = []
    for match in matches:
        day = timezone.localdate(match.starts_at)
        if groups and groups[-1][0] == day:
            groups[-1][1].append(match)
        else:
            groups.append((day, [match]))
    return groups


def facility_schedule(facility, user, page_number):
    """Upcoming games, recent results and game counts at one facility.

    Cancelled matches stay in the upcoming list, with their badge, but are
    never the next game and never count in the stats.
    """
    base = schedule_matches().filter(
        facility=facility, season__in=seasons_visible_to(user)
    )
    scheduled = base.scheduled()
    now = timezone.now()
    upcoming = base.filter(ends_at__gte=now).order_by("starts_at", "pk")
    page_obj = Paginator(upcoming, FACILITY_UPCOMING_PER_PAGE).get_page(page_number)
    semester = current_semester(timezone.localdate())
    counts = scheduled.aggregate(
        upcoming=Count("pk", filter=Q(ends_at__gte=now)),
        semester=Count(
            "pk",
            filter=Q(starts_at__date__range=(semester.start_date, semester.end_date)),
        ),
    )
    recent = scheduled.filter(
        ends_at__lt=now, home_score__isnull=False, away_score__isnull=False
    ).order_by("-starts_at", "-pk")[:FACILITY_RECENT_LIMIT]
    sport_counts = (
        scheduled.values(name=F("home_team__sport__name"))
        .annotate(count=Count("pk"))
        .order_by("-count", "name")
    )
    return {
        "page_obj": page_obj,
        "days": group_by_local_date(page_obj.object_list),
        "next_game": upcoming.scheduled().first(),
        "recent": list(recent),
        "upcoming_count": counts["upcoming"],
        "semester_count": counts["semester"],
        "sport_counts": list(sport_counts),
    }
