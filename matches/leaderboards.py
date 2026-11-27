"""Player leaderboards: players ranked by one stat of one sport (#311).

Only counted matches (the standings rule) in seasons the viewer can see count.
Players who untick "Show me on leaderboards" on their profile are left out.
Building the boards takes a fixed number of queries, whatever the number of
players, matches or event types.
"""

from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Sum

from profiles.models import PlayerProfile
from teams.event_types import scoring_event_type
from teams.models import EventType, Season, Sport, Team

from .models import MatchAppearance, PlayerStat
from .schedule import seasons_visible_to
from .standings import counted_matches
from .stats import _name_key, ordered_event_types, per_game, visible_counted_matches

LEADERBOARD_LIMIT = 25
# Fewer games than this and one big game would top the per-game column.
MIN_GAMES_FOR_PER_GAME = 3


@dataclass
class LeaderRow:
    rank: int
    player: object
    team: object  # The team of the player's latest counted match, or None.
    games: int
    total: int
    per_game: object  # A float, or None under MIN_GAMES_FOR_PER_GAME games.


@dataclass
class StatBoard:
    event_type: EventType
    rows: list = field(default_factory=list)


def leaderboard_sports():
    """Sports that have at least one event type, by name."""
    return Sport.objects.filter(event_types__isnull=False).distinct().order_by("name")


def leaderboard_seasons(user, sport):
    """Visible seasons with a counted match of the sport, newest first."""
    played = counted_matches().filter(home_team__sport=sport).values("season")
    return (
        seasons_visible_to(user)
        .filter(pk__in=played)
        .order_by("-start_date", "name", "pk")
    )


def _ranked(entries):
    """Competition ranks on the total: 1, 1, 3. entries are sorted already."""
    ranks, previous, rank = [], None, 0
    for position, entry in enumerate(entries, start=1):
        if entry["total"] != previous:
            rank, previous = position, entry["total"]
        ranks.append(rank)
    return ranks


def player_leaderboards(user, sport, season=None, limit=LEADERBOARD_LIMIT):
    """One StatBoard per event type of the sport, scoring stat first.

    season=None covers every visible season of the sport. Each board lists at
    most `limit` players with a total above 0, highest total first, then the
    higher per-game average, then by name.
    """
    event_types = list(EventType.objects.filter(sport=sport).order_by("name", "pk"))
    if not event_types:
        return []
    event_types = ordered_event_types(
        event_types, scoring_event_type(sport, event_types)
    )
    matches = visible_counted_matches(user).filter(home_team__sport=sport)
    if season is not None:
        matches = matches.filter(season=season)
    hidden = PlayerProfile.objects.filter(show_on_leaderboards=False).values("user_id")
    totals = {}
    for player_id, event_type_id, total in (
        PlayerStat.objects.filter(match__in=matches)
        .exclude(player_id__in=hidden)
        .values_list("player_id", "event_type_id")
        .annotate(total=Sum("value"))
    ):
        if total:
            totals.setdefault(event_type_id, []).append((player_id, total))
    appearances = MatchAppearance.objects.filter(match__in=matches).exclude(
        player_id__in=hidden
    )
    games = dict(
        appearances.values_list("player_id").annotate(n=Count("match", distinct=True))
    )

    # Rank first, then load only the players and teams the boards show.
    boards = []
    for event_type in event_types:
        entries = [
            {
                "player_id": player_id,
                "total": total,
                "games": games.get(player_id, 0),
                "per_game": (
                    per_game(total, games.get(player_id, 0))
                    if games.get(player_id, 0) >= MIN_GAMES_FOR_PER_GAME
                    else None
                ),
            }
            for player_id, total in totals.get(event_type.pk, [])
        ]
        boards.append((event_type, entries))
    shown_ids = {e["player_id"] for _, entries in boards for e in entries}
    players = get_user_model().objects.in_bulk(shown_ids)
    latest_team = {}
    for player_id, team_id, _ in (
        appearances.filter(player_id__in=shown_ids)
        .values_list("player_id", "team_id")
        .annotate(last=Max("match__starts_at"))
        .order_by("player_id", "last", "team_id")
    ):
        latest_team[player_id] = team_id  # The latest one wins.
    teams = Team.objects.select_related("sport", "division").in_bulk(
        set(latest_team.values())
    )

    result = []
    for event_type, entries in boards:
        entries = [e for e in entries if e["player_id"] in players]
        entries.sort(key=lambda e: _name_key(players[e["player_id"]])[1:])
        entries.sort(key=lambda e: (-e["total"], -(e["per_game"] or 0)))
        entries = entries[:limit]
        result.append(
            StatBoard(
                event_type=event_type,
                rows=[
                    LeaderRow(
                        rank=rank,
                        player=players[e["player_id"]],
                        team=teams.get(latest_team.get(e["player_id"])),
                        games=e["games"],
                        total=e["total"],
                        per_game=e["per_game"],
                    )
                    for rank, e in zip(_ranked(entries), entries)
                ],
            )
        )
    return result


def default_sport(user, sports):
    """The sport to show first.

    The sport of the viewer's newest team, else the sport of the latest
    counted match the viewer can see, else the first sport listed.
    """
    sport_ids = [sport.pk for sport in sports]
    pick = (
        Team.objects.filter(roster__player=user, sport_id__in=sport_ids)
        .order_by("-pk")
        .values_list("sport_id", flat=True)
        .first()
    ) or (
        visible_counted_matches(user)
        .filter(home_team__sport_id__in=sport_ids)
        .order_by("-starts_at", "-pk")
        .values_list("home_team__sport_id", flat=True)
        .first()
    )
    for sport in sports:
        if sport.pk == pick:
            return sport
    return sports[0] if sports else None


def season_for(seasons, season_id):
    """The season with this id among `seasons`, or None."""
    if not str(season_id).isdecimal():
        return None
    return next((s for s in seasons if s.pk == int(season_id)), None)


def sport_of_season(season_id):
    """The sport set on a season, for links that only pass the season."""
    if not str(season_id).isdecimal():
        return None
    return (
        Season.objects.filter(pk=season_id, sport__isnull=False)
        .values_list("sport_id", flat=True)
        .first()
    )
