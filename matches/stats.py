"""Period scores, appearances and player stats of one match.

team_sheets() and period_rows() read them. save_match_sheet() is the only writer.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum

from core.names import display_name
from teams.models import EventType, Roster, Team
from teams.season_rules import SeasonState

from .models import Match, MatchAppearance, MatchPeriodScore, PlayerStat
from .schedule import schedule_matches, seasons_visible_to
from .standings import counted_matches


@dataclass
class SheetRow:
    player: object
    on_roster: bool  # False: the player left the team after this match.
    played: bool = False  # Has a MatchAppearance for this team.
    stats: dict = field(default_factory=dict)  # event_type_id -> value; missing is 0.

    def values(self, event_types):
        """The stored values in the order of event_types, 0 when missing."""
        return [self.stats.get(event_type.pk, 0) for event_type in event_types]


@dataclass
class TeamSheet:
    team: Team
    rows: list  # Roster players by name, then players who left, by name.


def _name_key(user):
    name = user.get_full_name()
    return (not name, name.lower(), user.pk)


def match_event_types(match):
    return list(
        EventType.objects.filter(sport_id=match.home_team.sport_id).order_by("name")
    )


def team_sheets(match):
    """[home, away] sheets, in 3 queries whatever the roster size."""
    teams = [match.home_team, match.away_team]
    team_ids = [team.pk for team in teams]
    roster = defaultdict(dict)
    for entry in Roster.objects.filter(team_id__in=team_ids).select_related("player"):
        roster[entry.team_id][entry.player_id] = SheetRow(entry.player, True)
    leavers = defaultdict(dict)

    def row_for(team_id, player):
        row = roster[team_id].get(player.pk) or leavers[team_id].get(player.pk)
        if row is None:
            row = leavers[team_id][player.pk] = SheetRow(player, False)
        return row

    for stat in PlayerStat.objects.filter(match=match).select_related("player"):
        row_for(stat.team_id, stat.player).stats[stat.event_type_id] = stat.value
    for appearance in MatchAppearance.objects.filter(match=match).select_related(
        "player"
    ):
        row_for(appearance.team_id, appearance.player).played = True

    def ordered(rows):
        return sorted(rows.values(), key=lambda row: _name_key(row.player))

    return [
        TeamSheet(team, ordered(roster[team.pk]) + ordered(leavers[team.pk]))
        for team in teams
    ]


def period_rows(match):
    """(label, home, away) for each stored period, in order."""
    sport = match.home_team.sport
    return [
        (sport.period_name(row.period), row.home_points, row.away_points)
        for row in match.period_scores.all()
    ]


# --- Match page: top performers, totals and the team comparison (#255). ---
#
# Pure functions over team_sheets() and the loaded event types: 0 queries.

TOP_PERFORMER_LIMIT = 3


def ordered_event_types(event_types, scoring):
    """The scoring type first when it is in event_types, then the rest in order."""
    if scoring is None or scoring not in event_types:
        return list(event_types)
    return [scoring] + [t for t in event_types if t != scoring]


@dataclass
class Leader:
    player: object
    value: int
    event_type: object

    @property
    def short_name(self):
        """The last name, else display_name: "Lee", or "PlayNYU player"."""
        return (self.player.last_name or "").strip() or display_name(self.player)


@dataclass
class TeamLeaders:
    team: Team
    leaders: list  # Leader per event type, scoring type first, at most 3.


def top_performers(sheets, event_types, scoring, limit=TOP_PERFORMER_LIMIT):
    """One TeamLeaders per sheet, in sheet order.

    For each event type, the row with the highest value leads. A 0 never
    leads, and a tie goes to _name_key. Players who left can lead.
    """
    ordered = ordered_event_types(event_types, scoring)
    result = []
    for sheet in sheets:
        leaders = []
        for event_type in ordered:
            if len(leaders) == limit:
                break
            rows = [row for row in sheet.rows if row.stats.get(event_type.pk, 0) > 0]
            if not rows:
                continue
            best = min(
                rows,
                key=lambda row: (
                    -row.stats[event_type.pk],
                    *_name_key(row.player),
                ),
            )
            leaders.append(Leader(best.player, best.stats[event_type.pk], event_type))
        result.append(TeamLeaders(sheet.team, leaders))
    return result


def team_totals(sheet, event_types):
    """The sum of each event type over every row, players who left included."""
    return [
        sum(row.stats.get(event_type.pk, 0) for row in sheet.rows)
        for event_type in event_types
    ]


@dataclass
class ComparisonRow:
    event_type: object
    home: int
    away: int
    home_pct: int

    @property
    def away_pct(self):
        return 100 - self.home_pct


def comparison_rows(event_types, home_totals, away_totals, scoring):
    """One row per event type with a total above 0, scoring type first."""
    home_by_pk = {t.pk: v for t, v in zip(event_types, home_totals)}
    away_by_pk = {t.pk: v for t, v in zip(event_types, away_totals)}
    rows = []
    for event_type in ordered_event_types(event_types, scoring):
        home, away = home_by_pk[event_type.pk], away_by_pk[event_type.pk]
        if home == away == 0:
            continue
        rows.append(
            ComparisonRow(event_type, home, away, round(100 * home / (home + away)))
        )
    return rows


def _stored(match):
    stats = {
        (row.team_id, row.player_id, row.event_type_id): row
        for row in PlayerStat.objects.filter(match=match)
    }
    appearances = {
        (row.team_id, row.player_id): row
        for row in MatchAppearance.objects.filter(match=match)
    }
    return stats, appearances


def _appearances_to_keep(stats, played, players):
    """Checked Played boxes plus every player with a stat, within the sheet."""
    with_stats = {(team, player) for (team, player, _), value in stats.items() if value}
    return (set(played) | with_stats) & set(players)


def _check_one_team(keep, players, stored_stats, stored_appearances):
    # Rows outside the sheet (players who left) stay, so they count too.
    untouched = {pair for pair in stored_appearances if pair not in players} | {
        (team, player)
        for (team, player, _), row in stored_stats.items()
        if (team, player) not in players and row.value
    }
    teams_by_player = defaultdict(set)
    for team_id, player_id in keep | untouched:
        teams_by_player[player_id].add(team_id)
    twice = [pk for pk, teams in teams_by_player.items() if len(teams) > 1]
    if twice:
        users = get_user_model().objects.filter(pk__in=twice).order_by("pk")
        raise ValidationError(
            [f"{display_name(user)} can only play for one team." for user in users]
        )


def check_one_team(match, *, stats, played, players):
    """Raise ValidationError when the sheet has a player playing for both teams."""
    keep = _appearances_to_keep(stats, played, players)
    _check_one_team(keep, set(players), *_stored(match))


def _check_new_rows(match, new_pairs):
    """The rules of validate_match_player, for many new rows in 1 query.

    Only new rows get the roster check, so players who left keep their rows.
    """
    team_ids = {match.home_team_id, match.away_team_id}
    if any(team_id not in team_ids for team_id, _ in new_pairs):
        raise ValidationError("Choose a team in this match.")
    roster = set(
        Roster.objects.filter(team_id__in=team_ids).values_list("team_id", "player_id")
    )
    if new_pairs - roster:
        raise ValidationError("That player isn't on this team.")


def _check_periods(match, periods):
    """MatchPeriodScore.clean, without a query for each row."""
    sport = match.home_team.sport
    highest = sport.period_count + sport.MAX_OVERTIME_PERIODS
    if any(period > highest for period, _, _ in periods):
        raise ValidationError("Matches have at most 2 overtime periods.")


def save_match_sheet(
    match, *, periods, final, stats, played, players, allow_closed=False
):
    """Write periods, the final score, stats and appearances in one transaction.

    periods: [(period, home, away)], complete rows only. Their sums are the score.
    final: (home, away), used only when periods is empty.
    stats: {(team_id, player_id, event_type_id): value}. 0 deletes the row.
        MatchSheet only posts the sport's event types, so they aren't checked here.
    played: {(team_id, player_id)} with a Played box checked.
    players: the (team_id, player_id) pairs this sheet edits. Rows of other
        pairs (players who left) stay as they are.
    allow_closed: also write a closed season's match. Only seed_match_details
        sets it, to fill history. Cancelled matches are always refused.

    The query count doesn't grow with the roster or the number of event types.
    """
    with transaction.atomic():
        locked = (
            Match.objects.select_for_update(of=("self",))
            .select_related("season", "home_team__sport")
            .get(pk=match.pk)
        )
        # The season or match may have closed since the caller read it.
        closed = locked.season.state == SeasonState.CLOSED
        history = allow_closed and closed and not locked.is_cancelled
        if not (locked.can_change or history):
            raise ValidationError("This match can no longer be scored.")
        players = set(players)
        stored_stats, stored_appearances = _stored(locked)
        keep = _appearances_to_keep(stats, played, players)
        _check_one_team(keep, players, stored_stats, stored_appearances)

        new_stats = [
            key for key, value in stats.items() if value and key not in stored_stats
        ]
        new_appearances = keep - set(stored_appearances)
        _check_new_rows(
            locked,
            {(team, player) for team, player, _ in new_stats} | new_appearances,
        )
        _check_periods(locked, periods)

        MatchPeriodScore.objects.filter(match=locked).delete()
        MatchPeriodScore.objects.bulk_create(
            MatchPeriodScore(
                match=locked, period=period, home_points=home, away_points=away
            )
            for period, home, away in periods
        )
        if periods:
            final = (sum(p[1] for p in periods), sum(p[2] for p in periods))
        locked.home_score, locked.away_score = final
        locked.save(update_fields=["home_score", "away_score"])

        changed, removed = [], []
        for key, value in stats.items():
            row = stored_stats.get(key)
            if row is None:
                continue
            if not value:
                removed.append(row.pk)
            elif row.value != value:
                row.value = value
                changed.append(row)
        if removed:
            PlayerStat.objects.filter(pk__in=removed).delete()
        if changed:
            PlayerStat.objects.bulk_update(changed, ["value"])
        PlayerStat.objects.bulk_create(
            PlayerStat(
                match=locked,
                team_id=team_id,
                player_id=player_id,
                event_type_id=event_type_id,
                value=stats[(team_id, player_id, event_type_id)],
            )
            for team_id, player_id, event_type_id in new_stats
        )

        gone = [
            row.pk
            for pair, row in stored_appearances.items()
            if pair in players and pair not in keep
        ]
        if gone:
            MatchAppearance.objects.filter(pk__in=gone).delete()
        MatchAppearance.objects.bulk_create(
            MatchAppearance(match=locked, team_id=team_id, player_id=player_id)
            for team_id, player_id in new_appearances
        )

    match.home_score, match.away_score = locked.home_score, locked.away_score


# --- Team and player pages: batch stat selectors. ---
#
# Each selector calls seasons_visible_to(user) once and reuses it, so the
# query count stays fixed whatever the rosters and matches hold.


def visible_counted_matches(user):
    """Counted matches in seasons the user can see."""
    return counted_matches().filter(season__in=seasons_visible_to(user))


def per_game(total, games):
    """A per-game average, or None with no games (shown as –)."""
    if not games:
        return None
    return round(total / games, 1)


def games_played(user, *, player_ids=None, team_ids=None):
    """{(player id, team id): games} in the user's visible counted matches.

    One query on MatchAppearance.
    """
    appearances = MatchAppearance.objects.filter(
        match__in=visible_counted_matches(user)
    )
    if player_ids is not None:
        appearances = appearances.filter(player_id__in=list(player_ids))
    if team_ids is not None:
        appearances = appearances.filter(team_id__in=list(team_ids))
    return {
        (row["player_id"], row["team_id"]): row["n"]
        for row in appearances.values("player_id", "team_id").annotate(
            n=Count("match", distinct=True)
        )
    }


def team_stat_totals(team, user):
    """[{"event_type", "total"}] for each of the team's sport's event types.

    Ordered by name, with zeros for event types nobody recorded.
    """
    matches = visible_counted_matches(user)
    sums = dict(
        PlayerStat.objects.filter(match__in=matches, team=team)
        .values_list("event_type_id")
        .annotate(total=Sum("value"))
    )
    return [
        {"event_type": event_type, "total": sums.get(event_type.pk, 0)}
        for event_type in EventType.objects.filter(sport_id=team.sport_id).order_by(
            "name"
        )
    ]


def team_player_stats(team, user):
    """(event types, rows) for the team's leaderboard table.

    Rows cover roster players and players with an appearance for the team in
    the user's visible counted matches. Each row has the player, their games
    and one value per event type. Rows sort by games played, then name.
    """
    matches = visible_counted_matches(user)
    event_types = list(
        EventType.objects.filter(sport_id=team.sport_id).order_by("name")
    )
    roster_ids = set(
        Roster.objects.filter(team=team).values_list("player_id", flat=True)
    )
    appearance_ids = set(
        MatchAppearance.objects.filter(match__in=matches, team=team)
        .values_list("player_id", flat=True)
        .distinct()
    )
    player_ids = roster_ids | appearance_ids
    players = get_user_model().objects.in_bulk(player_ids)
    game_counts = dict(
        MatchAppearance.objects.filter(match__in=matches, team=team)
        .values_list("player_id")
        .annotate(n=Count("match", distinct=True))
    )
    stat_sums = {
        (player_id, event_type_id): total
        for player_id, event_type_id, total in PlayerStat.objects.filter(
            match__in=matches, team=team
        )
        .values_list("player_id", "event_type_id")
        .annotate(total=Sum("value"))
    }
    rows = [
        {
            "player": players[player_id],
            "games": game_counts.get(player_id, 0),
            "values": [
                stat_sums.get((player_id, event_type.pk), 0)
                for event_type in event_types
            ],
        }
        for player_id in player_ids
        if player_id in players
    ]
    rows.sort(key=lambda row: (-row["games"], *_name_key(row["player"])[1:]))
    return event_types, rows


def player_season_stats(player, user):
    """[{"team", "season", "games", "rows"}] for the player's visible teams.

    Newest season first. Each block holds one row per event type of the
    team's sport, with the total and the per-game average. Teams come from
    the player's appearances, stat rows and roster entries in visible
    seasons, so a season stays after the player leaves its roster. Runs 4
    queries: teams, games, stat sums and event types.
    """
    seasons = seasons_visible_to(user)
    matches = counted_matches().filter(season__in=seasons)
    teams = list(
        Team.objects.filter(Q(season__isnull=True) | Q(season__in=seasons))
        .filter(
            Q(match_appearances__player=player, match_appearances__match__in=matches)
            | Q(player_stats__player=player, player_stats__match__in=matches)
            | Q(roster__player=player)
        )
        .select_related("season", "sport")
        .distinct()
    )
    team_ids = [team.pk for team in teams]
    game_counts = dict(
        MatchAppearance.objects.filter(
            player=player, match__in=matches, team_id__in=team_ids
        )
        .values_list("team_id")
        .annotate(n=Count("match", distinct=True))
    )
    stat_sums = {
        (team_id, event_type_id): total
        for team_id, event_type_id, total in PlayerStat.objects.filter(
            player=player, match__in=matches, team_id__in=team_ids
        )
        .values_list("team_id", "event_type_id")
        .annotate(total=Sum("value"))
    }
    types_by_sport = {}
    for event_type in EventType.objects.filter(
        sport_id__in={team.sport_id for team in teams}
    ).order_by("name"):
        types_by_sport.setdefault(event_type.sport_id, []).append(event_type)
    teams.sort(key=lambda team: team.name.lower())
    teams.sort(key=_newest_season_first, reverse=True)
    blocks = []
    for team in teams:
        games = game_counts.get(team.pk, 0)
        blocks.append(
            {
                "team": team,
                "season": team.season,
                "games": games,
                "rows": [
                    {
                        "event_type": event_type,
                        "total": stat_sums.get((team.pk, event_type.pk), 0),
                        "per_game": per_game(
                            stat_sums.get((team.pk, event_type.pk), 0), games
                        ),
                    }
                    for event_type in types_by_sport.get(team.sport_id, [])
                ],
            }
        )
    return blocks


def _newest_season_first(team):
    """Sort key: teams with a season first, newest start date first."""
    if team.season_id is None or team.season is None:
        return (False, datetime.date.min)
    return (True, team.season.start_date)


def player_recent_lines(player, user, limit=5):
    """The player's counted visible matches, newest first, with own stats.

    Built on schedule_matches(). Each match gets `player_line`: the
    player's own PlayerStat rows, ordered by event type name.
    """
    seasons = seasons_visible_to(user)
    return list(
        schedule_matches()
        .filter(
            appearances__player=player,
            status=Match.Status.SCHEDULED,
            home_score__isnull=False,
            away_score__isnull=False,
            season__in=seasons,
        )
        .prefetch_related(
            Prefetch(
                "player_stats",
                queryset=PlayerStat.objects.filter(player=player)
                .select_related("event_type")
                .order_by("event_type__name"),
                to_attr="player_line",
            )
        )
        .order_by("-starts_at", "-pk")[:limit]
    )
