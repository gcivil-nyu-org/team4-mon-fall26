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
            "pk", "starts_at", "home_team_id", "away_team_id", "home_score", "away_score"
        )
    ]


def season_teams(match):
    """The season's teams with their divisions, by name, in 1 query."""
    return list(
        Team.objects.filter(season_id=match.season_id)
        .select_related("division")
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


def _place(standing, team):
    """(position, of, label) in the team's division table, else the season's."""
    if team.division_id is not None:
        return (
            standing["division_position"],
            standing["division_of"],
            team.division.name,
        )
    return standing["position"], standing["of"], None


def standings_movement(match, teams, results):
    """[home, away] Movement across this match, or None when it isn't counted.

    "Before" is every counted result with a smaller (starts_at, pk) key.
    "After" is before plus this match. Later matches change neither.
    """
    if not match.has_result or match.is_cancelled:
        return None
    key = (match.starts_at, match.pk)
    before = positions(
        rank_rows(teams, _scores(r for r in results if (r.starts_at, r.pk) < key))
    )
    after = positions(
        rank_rows(teams, _scores(r for r in results if (r.starts_at, r.pk) <= key))
    )
    movements = []
    for team in (match.home_team, match.away_team):
        if team.pk not in after:
            continue
        before_position, _, _ = _place(before[team.pk], team)
        after_position, of, label = _place(after[team.pk], team)
        if before[team.pk]["row"]["played"] == 0:
            direction, change, before_position = "first", 0, None
        else:
            change = before_position - after_position
            direction = "up" if change > 0 else "down" if change < 0 else "same"
        movements.append(
            Movement(
                team,
                label,
                before_position,
                after_position,
                of,
                before[team.pk]["row"]["points"],
                after[team.pk]["row"]["points"],
                direction,
                change,
            )
        )
    return movements
