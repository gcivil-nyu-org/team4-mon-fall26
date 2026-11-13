"""Season standings computed from recorded match scores.

A match counts when it isn't cancelled and both scores are set. A win is
3 points and a draw is 1, so correcting a score just recomputes the table.
"""

from django.db.models import Q

from .models import Match

WIN_POINTS = 3
DRAW_POINTS = 1


def compute_standings(season, division=None):
    """One row per team of the season, ordered like the leaderboard.

    Each row is a dict with the team, P/W/D/L and Pts. Teams with no
    recorded matches still appear, with zeros.

    With a division, only that division's teams are listed, ranked among
    themselves. Their records still count every match they played in the
    season, including the ones against other divisions.
    """
    from teams.models import Team

    teams = list(
        Team.objects.filter(season=season).select_related("division").order_by("name")
    )
    rows = {
        team.pk: {
            "team": team,
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "points": 0,
        }
        for team in teams
    }
    matches = (
        Match.objects.filter(
            season=season,
            status=Match.Status.SCHEDULED,
            home_score__isnull=False,
            away_score__isnull=False,
        )
        .select_related("home_team", "away_team")
        .filter(
            Q(home_team__season=season) & Q(away_team__season=season),
        )
    )
    for match in matches:
        home = rows.get(match.home_team_id)
        away = rows.get(match.away_team_id)
        if home is None or away is None:
            continue
        home["played"] += 1
        away["played"] += 1
        if match.home_score > match.away_score:
            home["won"] += 1
            home["points"] += WIN_POINTS
            away["lost"] += 1
        elif match.home_score < match.away_score:
            away["won"] += 1
            away["points"] += WIN_POINTS
            home["lost"] += 1
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += DRAW_POINTS
            away["points"] += DRAW_POINTS
    listed = rows.values()
    if division is not None:
        listed = [row for row in listed if row["team"].division_id == division.pk]
    return sorted(
        listed,
        key=lambda row: (-row["points"], -row["won"], row["team"].name),
    )


def team_records(team_ids):
    """All-time {team id: record} for the given teams, in one query.

    A record is a dict with played, won, drawn and lost. A match counts by
    the same rule as the standings: not cancelled, both scores set.
    """
    records = {
        team_id: {"played": 0, "won": 0, "drawn": 0, "lost": 0} for team_id in team_ids
    }
    if not records:
        return records
    matches = Match.objects.filter(
        Q(home_team__in=list(records)) | Q(away_team__in=list(records)),
        status=Match.Status.SCHEDULED,
        home_score__isnull=False,
        away_score__isnull=False,
    ).values_list("home_team_id", "away_team_id", "home_score", "away_score")
    for home_id, away_id, home_score, away_score in matches:
        for team_id, scored, conceded in (
            (home_id, home_score, away_score),
            (away_id, away_score, home_score),
        ):
            record = records.get(team_id)
            if record is None:
                continue
            record["played"] += 1
            if scored > conceded:
                record["won"] += 1
            elif scored < conceded:
                record["lost"] += 1
            else:
                record["drawn"] += 1
    return records


def player_record(team_ids):
    """The all-time record across the given teams: their team_records, summed."""
    return total_record(team_records(team_ids))


def total_record(records):
    """One record summing what team_records() returned."""
    total = {"played": 0, "won": 0, "drawn": 0, "lost": 0}
    for record in records.values():
        for key in total:
            total[key] += record[key]
    return total


def dashboard_standings(user, today):
    """This semester's standings for the dashboard: (semester label, tabs).

    One tab per sport with a visible default season for the current term.
    The player's sports come first, most recently joined first; the rest
    follow by name. Each row gets `is_me` when the player is on that team.
    """
    from teams.models import Roster
    from teams.semesters import current_semester

    from .schedule import seasons_visible_to

    semester = current_semester(today)
    seasons = (
        seasons_visible_to(user)
        .filter(term=semester.term, sport__isnull=False)
        .select_related("sport")
    )
    entries = Roster.objects.filter(player=user).order_by("-joined_at")
    my_team_ids = set()
    my_sport_rank = {}
    for team_id, sport_id in entries.values_list("team_id", "team__sport_id"):
        my_team_ids.add(team_id)
        my_sport_rank.setdefault(sport_id, len(my_sport_rank))

    tabs = []
    for season in seasons:
        rows = compute_standings(season)
        for row in rows:
            row["is_me"] = row["team"].pk in my_team_ids
        tabs.append(
            {
                "sport": season.sport,
                "season": season,
                "is_mine": season.sport_id in my_sport_rank,
                "rows": rows,
            }
        )
    tabs.sort(
        key=lambda tab: (
            my_sport_rank.get(tab["sport"].pk, len(my_sport_rank)),
            tab["sport"].name.lower(),
        )
    )
    return semester.label, tabs
