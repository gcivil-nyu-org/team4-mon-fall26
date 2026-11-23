"""Season context of one match: team form, head-to-head and standings movement.

season_teams() and season_results() run 1 query each. The other functions
are pure: they read those two lists, so the match page's query count stays
fixed whatever the season size (#255).
"""

from dataclasses import dataclass
from typing import NamedTuple

from teams.models import Team

from .standings import counted_matches, positions, rank_rows


class Result(NamedTuple):
    pk: int
    starts_at: object
    home_id: int
    away_id: int
    home_score: int
    away_score: int


def season_results(match):
    """The season's counted results by (starts_at, pk), in 1 query."""
    return [
        Result(*row)
        for row in counted_matches()
        .filter(season_id=match.season_id)
        .order_by("starts_at", "pk")
        .values_list(
            "pk",
            "starts_at",
            "home_team_id",
            "away_team_id",
            "home_score",
            "away_score",
        )
    ]


def season_teams(match):
    """The season's teams with their divisions and sports, by name, in 1 query."""
    return list(
        Team.objects.filter(season_id=match.season_id)
        .select_related("division", "sport")
        .order_by("name")
    )


def _scores(results):
    return [(r.home_id, r.away_id, r.home_score, r.away_score) for r in results]


@dataclass
class Form:
    match_pk: int
    letter: str  # "W", "D" or "L", from this team's side.
    scored: int
    conceded: int
    opponent: object
    starts_at: object
    is_this_match: bool


@dataclass
class TeamContext:
    team: object
    row: dict  # The rank_rows() row.
    standing: dict  # The positions() entry.
    form: list  # Newest first.


def _letter(scored, conceded):
    if scored > conceded:
        return "W"
    if scored < conceded:
        return "L"
    return "D"


def _form(team, match, results, by_pk, limit):
    form = []
    for r in reversed(results):
        if len(form) == limit:
            break
        if team.pk == r.home_id:
            opponent_id, scored, conceded = r.away_id, r.home_score, r.away_score
        elif team.pk == r.away_id:
            opponent_id, scored, conceded = r.home_id, r.away_score, r.home_score
        else:
            continue
        opponent = by_pk.get(opponent_id)
        if opponent is None:
            continue
        form.append(
            Form(
                r.pk,
                _letter(scored, conceded),
                scored,
                conceded,
                opponent,
                r.starts_at,
                r.pk == match.pk,
            )
        )
    return form


def recent_form(team, matches, limit=5):
    """The team's last results as Forms, newest first, from loaded matches.

    Counts the same matches as the standings: not cancelled, both scores set.
    """
    played = sorted(
        (m for m in matches if m.has_result and not m.is_cancelled),
        key=lambda m: (m.starts_at, m.pk),
        reverse=True,
    )
    form = []
    for m in played[:limit]:
        if m.home_team_id == team.pk:
            scored, conceded, opponent = m.home_score, m.away_score, m.away_team
        else:
            scored, conceded, opponent = m.away_score, m.home_score, m.home_team
        form.append(
            Form(
                m.pk,
                _letter(scored, conceded),
                scored,
                conceded,
                opponent,
                m.starts_at,
                False,
            )
        )
    return form


def team_context(match, teams, results, limit=5):
    """[home, away] TeamContext for the season today, later matches included."""
    rows = rank_rows(teams, _scores(results))
    standings = positions(rows)
    by_pk = {team.pk: team for team in teams}
    context = []
    for team in (match.home_team, match.away_team):
        standing = standings.get(team.pk)
        context.append(
            TeamContext(
                team,
                standing["row"] if standing else None,
                standing,
                _form(team, match, results, by_pk, limit),
            )
        )
    return context


@dataclass
class HeadToHead:
    home_wins: int  # Wins of match.home_team, whichever side it played.
    draws: int
    away_wins: int
    meetings: list  # Result tuples, newest first.


def head_to_head(match, results):
    """This season's results between the two teams of the match."""
    pair = {match.home_team_id, match.away_team_id}
    meetings = [r for r in reversed(results) if {r.home_id, r.away_id} == pair]
    home_wins = draws = away_wins = 0
    for r in meetings:
        home_side = r.home_id == match.home_team_id
        scored, conceded = (
            (r.home_score, r.away_score) if home_side else (r.away_score, r.home_score)
        )
        letter = _letter(scored, conceded)
        if letter == "W":
            home_wins += 1
        elif letter == "L":
            away_wins += 1
        else:
            draws += 1
    return HeadToHead(home_wins, draws, away_wins, meetings)


@dataclass
class Movement:
    team: object
    table_label: object  # The division name, or None for the season table.
    before_position: object  # None for "first".
    after_position: int
    of: int
    before_points: int
    after_points: int
    direction: str  # "up", "down", "same" or "first".
    change: int  # before_position - after_position; 0 for "first".

    @property
    def places(self):
        """The size of the move, for "Up 2 places"."""
        return abs(self.change)

    @property
    def points_change(self):
        return self.after_points - self.before_points


def table_division(match):
    """The division both teams share, else None for the season table."""
    home, away = match.home_team, match.away_team
    if home.division_id is not None and home.division_id == away.division_id:
        return home.division
    return None


def _table(teams, results, division):
    """{team id: (position, row)} in the season table, or in one division's."""
    rows = rank_rows(teams, _scores(results))
    if division is not None:
        rows = [row for row in rows if row["team"].division_id == division.pk]
    return {row["team"].pk: (position, row) for position, row in enumerate(rows, 1)}


@dataclass
class TableRow:
    position: int
    row: dict  # The rank_rows() row, after this match.
    movement: object  # Movement for the two match teams, else None.


@dataclass
class StandingsTable:
    division: object  # The shared division, or None for the season table.
    rows: list  # TableRow per team, by position after this match.
    movements: list  # [home, away] Movement.


def standings_table(match, teams, results):
    """The table after this match, with movement markers, or None.

    It is None when the match isn't counted. The table is the division
    both teams share, else the season table. "Before" is every counted
    result with a smaller (starts_at, pk) key; "after" adds this match.
    Later matches change neither.
    """
    if not match.has_result or match.is_cancelled:
        return None
    key = (match.starts_at, match.pk)
    division = table_division(match)
    before = _table(teams, [r for r in results if (r.starts_at, r.pk) < key], division)
    after = _table(teams, [r for r in results if (r.starts_at, r.pk) <= key], division)
    label = division.name if division is not None else None
    movements = {}
    for team in (match.home_team, match.away_team):
        if team.pk not in after:
            continue
        before_position, before_row = before[team.pk]
        after_position, after_row = after[team.pk]
        if before_row["played"] == 0:
            direction, change, before_position = "first", 0, None
        else:
            change = before_position - after_position
            direction = "up" if change > 0 else "down" if change < 0 else "same"
        movements[team.pk] = Movement(
            team,
            label,
            before_position,
            after_position,
            len(after),
            before_row["points"],
            after_row["points"],
            direction,
            change,
        )
    rows = [
        TableRow(position, row, movements.get(team_id))
        for team_id, (position, row) in sorted(
            after.items(), key=lambda item: item[1][0]
        )
    ]
    return StandingsTable(division, rows, list(movements.values()))


def standings_movement(match, teams, results):
    """[home, away] Movement across this match, or None when it isn't counted."""
    table = standings_table(match, teams, results)
    return None if table is None else table.movements
