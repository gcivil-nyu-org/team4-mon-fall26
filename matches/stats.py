"""Period scores, appearances and player stats of one match.

team_sheets() and period_rows() read them. save_match_sheet() is the only writer.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from core.templatetags.ui import player_name
from teams.models import EventType, Roster, Team

from .models import Match, MatchAppearance, MatchPeriodScore, PlayerStat


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
            [f"{player_name(user)} can only play for one team." for user in users]
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


def save_match_sheet(match, *, periods, final, stats, played, players):
    """Write periods, the final score, stats and appearances in one transaction.

    periods: [(period, home, away)], complete rows only. Their sums are the score.
    final: (home, away), used only when periods is empty.
    stats: {(team_id, player_id, event_type_id): value}. 0 deletes the row.
        MatchSheet only posts the sport's event types, so they aren't checked here.
    played: {(team_id, player_id)} with a Played box checked.
    players: the (team_id, player_id) pairs this sheet edits. Rows of other
        pairs (players who left) stay as they are.

    The query count doesn't grow with the roster or the number of event types.
    """
    with transaction.atomic():
        locked = (
            Match.objects.select_for_update(of=("self",))
            .select_related("season", "home_team__sport")
            .get(pk=match.pk)
        )
        # The season or match may have closed since the caller read it.
        if not locked.can_change:
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
