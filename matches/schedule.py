"""What players can see of the league's matches on the schedule pages.

Cancelled matches stay in on purpose: the pages mark them instead of hiding them.
"""

from dataclasses import dataclass

from django.core.paginator import Paginator
from django.db.models import Count, F, Q, prefetch_related_objects
from django.db.models.functions import Lower
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from teams.event_types import scoring_event_type
from teams.models import EventType, Roster, Season
from teams.semesters import current_semester

from .models import Match, PlayerStat


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


# --- The schedule table (/matches/schedule/). ---

SCHEDULE_PER_PAGE = 50
SCHEDULE_TABS = ("upcoming", "results", "all")
# Upcoming shows the soonest first, results the newest first.
DEFAULT_SORTS = {"upcoming": "date", "results": "-date", "all": "date"}
# The sortable columns. Each key also sorts in reverse with a "-" prefix.
# Names sort case-insensitively, and ties go by start time.
SORT_COLUMNS = {
    "date": None,
    "sport": "home_team__sport__name",
    "home": "home_team__name",
    "away": "away_team__name",
    "venue": "facility__name",
}
SCHEDULE_SORTS = tuple(
    sort for key in SORT_COLUMNS for sort in (key, f"-{key}")
)  # The allowlist: date, -date, sport, -sport, ...


def schedule_order(sort):
    """The order_by() arguments for an allowlisted sort such as "-home"."""
    descending = sort.startswith("-")
    column = SORT_COLUMNS[sort.removeprefix("-")]
    if column is None:
        return ["-starts_at", "-pk"] if descending else ["starts_at", "pk"]
    name = Lower(column)
    return [name.desc() if descending else name.asc(), "starts_at", "pk"]


def schedule_tab(matches, tab):
    """Upcoming matches haven't ended yet, and results have. "all" keeps both.

    A match being played is upcoming, like on the team page.
    """
    now = timezone.now()
    if tab == "upcoming":
        return matches.filter(ends_at__gte=now)
    if tab == "results":
        return matches.filter(ends_at__lt=now)
    return matches


@dataclass
class TopPerformer:
    player: object
    value: int
    event_type: object


def scoring_event_types(sport_ids):
    """{sport id: the sport's scoring EventType}, in 1 query.

    The rule is teams.event_types.scoring_event_type: the type marked
    is_scoring, else one named Points or Goals. A sport with no scoring
    type is left out, so its matches show no top performer.
    """
    by_sport = {}
    for event_type in EventType.objects.filter(sport_id__in=sport_ids).order_by(
        "name", "pk"
    ):
        by_sport.setdefault(event_type.sport_id, []).append(event_type)
    scoring = {}
    for sport_id, types in by_sport.items():
        chosen = scoring_event_type(sport_id, types)
        if chosen is not None:
            scoring[sport_id] = chosen
    return scoring


def period_line(match):
    """ "Q 14-12 18-15 OT1 3-2": the sport's label, then home-away per period.

    Overtime periods get their own OT1 and OT2 labels, as on the match page.
    """
    sport = match.home_team.sport
    regular, overtime = [], []
    for row in match.period_scores.all():
        pair = f"{row.home_points}-{row.away_points}"
        if row.period > sport.period_count:
            overtime.append(f"{sport.period_name(row.period)} {pair}")
        else:
            regular.append(pair)
    if regular:
        regular.insert(0, sport.period_label)
    return " ".join(regular + overtime)


def _name_key(user):
    name = user.get_full_name()
    return (not name, name.lower(), user.pk)


def annotate_schedule_rows(matches):
    """Give each match `period_line` and `top_performer`, in 3 queries.

    The matches come from schedule_matches(). The queries: the period
    prefetch, the scoring event types, and their stats in these matches.
    The top performer has the highest value of the sport's scoring event
    type; a tie goes by name. It is None with no result, for a cancelled
    match, and with no stat of that event type.
    """
    matches = list(matches)
    prefetch_related_objects(matches, "period_scores")
    scored = {m.pk: m for m in matches if m.has_result and not m.is_cancelled}
    types = scoring_event_types({m.home_team.sport_id for m in scored.values()})
    best = {}
    stats = PlayerStat.objects.filter(
        match_id__in=list(scored), event_type__in=list(types.values())
    ).select_related("player")
    for stat in stats:
        # Each sport's scoring type only, never another sport's.
        scoring = types.get(scored[stat.match_id].home_team.sport_id)
        if scoring is None or stat.event_type_id != scoring.pk:
            continue
        key = (-stat.value, *_name_key(stat.player))
        if stat.match_id not in best or key < best[stat.match_id][0]:
            best[stat.match_id] = (key, stat)
    for match in matches:
        match.period_line = period_line(match)
        match.top_performer = None
        if match.pk in best:
            stat = best[match.pk][1]
            match.top_performer = TopPerformer(
                stat.player, stat.value, types[match.home_team.sport_id]
            )
    return matches
