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
