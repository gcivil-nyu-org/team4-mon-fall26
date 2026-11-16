"""Tests for the team and player stat selectors in matches/stats.py."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from teams.models import EventType, Roster, Season
from teams.season_rules import SeasonState

from .models import MatchAppearance, PlayerStat
from .stats import (
    games_played,
    per_game,
    player_recent_lines,
    player_season_stats,
    team_player_stats,
    team_stat_totals,
)
from .tests import MatchFixtures, at, make_user


def count_queries(func):
    with CaptureQueriesContext(connection) as ctx:
        func()
    return len(ctx.captured_queries)


class StatFixtures(MatchFixtures):
    """Match fixtures plus scored-stat helpers."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.goal = EventType.objects.create(sport=cls.soccer, name="Goal")
        cls.assist = EventType.objects.create(sport=cls.soccer, name="Assist")
        cls.scorer = make_user("scorer")
        Roster.objects.create(team=cls.home, player=cls.scorer)

    def play(self, match, player, team, **stats):
        """Save the match, then record an appearance and stat values."""
        if match.pk is None:
            match.save()
        MatchAppearance.objects.create(match=match, player=player, team=team)
        for name, value in stats.items():
            event_type = {"goal": self.goal, "assist": self.assist}[name]
            if value:
                PlayerStat.objects.create(
                    match=match,
                    player=player,
                    team=team,
                    event_type=event_type,
                    value=value,
                )
        return match

    def scored(self, day=10, **overrides):
        values = {"home_score": 1, "away_score": 0}
        values.update(overrides)
        return self.build(starts_at=at(day, 18), ends_at=at(day, 20), **values)


class PerGameTests(TestCase):
    def test_rounds_to_one_decimal(self):
        self.assertEqual(per_game(5, 3), 1.7)

    def test_zero_total_is_zero(self):
        self.assertEqual(per_game(0, 2), 0.0)

    def test_no_games_is_none(self):
        self.assertIsNone(per_game(3, 0))


class GamesPlayedTests(StatFixtures):
    def test_counts_only_counted_matches(self):
        scored = self.scored()
        scored.save()
        unscored = self.build(starts_at=at(12, 18), ends_at=at(12, 20))
        unscored.save()
        cancelled = self.build(starts_at=at(13, 18), ends_at=at(13, 20))
        cancelled.save()
        cancelled.cancel()
        for match in (scored, unscored, cancelled):
            MatchAppearance.objects.create(
                match=match, player=self.scorer, team=self.home
            )
        self.assertEqual(
            games_played(self.player, player_ids=[self.scorer.pk]),
            {(self.scorer.pk, self.home.pk): 1},
        )

    def test_draft_season_hidden_from_players(self):
        match = self.scored()
        match.save()
        MatchAppearance.objects.create(match=match, player=self.scorer, team=self.home)
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.DRAFT)
        self.assertEqual(games_played(self.player, player_ids=[self.scorer.pk]), {})
        self.assertEqual(len(games_played(self.admin, player_ids=[self.scorer.pk])), 1)


class TeamStatTotalsTests(StatFixtures):
    def test_sums_and_zero_rows(self):
        self.play(self.scored(day=10), self.scorer, self.home, goal=2)
        self.play(self.scored(day=11), self.scorer, self.home, goal=1)
        self.assertEqual(
            [
                (row["event_type"].name, row["total"])
                for row in team_stat_totals(self.home, self.player)
            ],
            [("Assist", 0), ("Goal", 3)],
        )

    def test_skips_unscored_matches(self):
        match = self.build(starts_at=at(10, 18), ends_at=at(10, 20))
        match.save()
        MatchAppearance.objects.create(match=match, player=self.scorer, team=self.home)
        PlayerStat.objects.create(
            match=match,
            player=self.scorer,
            team=self.home,
            event_type=self.goal,
            value=2,
        )
        totals = {
            row["event_type"].name: row["total"]
            for row in team_stat_totals(self.home, self.player)
        }
        self.assertEqual(totals["Goal"], 0)


class TeamPlayerStatsTests(StatFixtures):
    def test_values_line_up_with_event_types(self):
        self.play(self.scored(), self.scorer, self.home, goal=2)
        event_types, rows = team_player_stats(self.home, self.player)
        self.assertEqual([e.name for e in event_types], ["Assist", "Goal"])
        row = next(r for r in rows if r["player"] == self.scorer)
        self.assertEqual((row["games"], row["values"]), (1, [0, 2]))

    def test_includes_roster_players_without_appearances(self):
        self.play(self.scored(), self.scorer, self.home, goal=2)
        Roster.objects.create(team=self.home, player=self.player)
        event_types, rows = team_player_stats(self.home, self.player)
        by_player = {r["player"].pk: r for r in rows}
        self.assertIn(self.player.pk, by_player)
        self.assertEqual(by_player[self.player.pk]["games"], 0)

    def test_orders_by_games_then_name(self):
        amy = make_user("amy")
        amy.first_name = "Amy"
        amy.save()
        zed = make_user("zed")
        zed.first_name = "Zed"
        zed.save()
        for newcomer in (amy, zed):
            Roster.objects.create(team=self.home, player=newcomer)
        self.play(self.scored(day=10), self.scorer, self.home, goal=1)
        self.play(self.scored(day=11), self.scorer, self.home, goal=1)
        self.play(self.scored(day=12), zed, self.home, goal=5)
        self.play(self.scored(day=13), amy, self.home, goal=5)
        event_types, rows = team_player_stats(self.home, self.player)
        self.assertEqual(
            [r["player"].pk for r in rows if r["games"] > 0],
            [self.scorer.pk, amy.pk, zed.pk],
        )

    def test_query_count_is_fixed(self):
        self.play(self.scored(), self.scorer, self.home, goal=2)
        extras = []
        for index in range(4):
            player = make_user(f"extra{index}")
            Roster.objects.create(team=self.home, player=player)
            extras.append(player)
        small = count_queries(lambda: team_player_stats(self.home, self.player))
        for day in range(11, 14):
            for player in extras:
                self.play(self.scored(day=day), player, self.home, goal=1)
        self.assertEqual(
            count_queries(lambda: team_player_stats(self.home, self.player)), small
        )


class PlayerSeasonStatsTests(StatFixtures):
    def test_per_game_and_newest_first(self):
        self.play(self.scored(day=10), self.scorer, self.home, goal=2)
        self.play(self.scored(day=11), self.scorer, self.home, goal=1)
        spring = self.build(
            season=self.other_season,
            home_team=self.outsider,
            away_team=self.make_team("Rivals", self.soccer, self.other_season),
            starts_at=at(12, 18),
            ends_at=at(12, 20),
            home_score=1,
            away_score=0,
        )
        self.play(spring, self.scorer, self.outsider, goal=1)
        blocks = player_season_stats(self.scorer, self.player)
        self.assertEqual([b["team"] for b in blocks], [self.outsider, self.home])
        fall = next(b for b in blocks if b["team"] == self.home)
        self.assertEqual(fall["games"], 2)
        goal_row = next(r for r in fall["rows"] if r["event_type"] == self.goal)
        self.assertEqual((goal_row["total"], goal_row["per_game"]), (3, 1.5))

    def test_keeps_season_after_leaving_roster(self):
        self.play(self.scored(), self.scorer, self.home, goal=1)
        Roster.objects.filter(team=self.home, player=self.scorer).delete()
        blocks = player_season_stats(self.scorer, self.player)
        self.assertEqual([b["team"] for b in blocks], [self.home])

    def test_hides_draft_seasons_from_players(self):
        self.play(self.scored(), self.scorer, self.home, goal=1)
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.DRAFT)
        self.assertEqual(player_season_stats(self.scorer, self.player), [])
        self.assertEqual(len(player_season_stats(self.scorer, self.admin)), 1)


class PlayerRecentLinesTests(StatFixtures):
    def lines(self, days=6, prefix=""):
        other = make_user(f"{prefix}other")
        Roster.objects.create(team=self.home, player=other)
        for day in range(1, days + 1):
            match = self.play(self.scored(day=day), self.scorer, self.home, goal=2)
            MatchAppearance.objects.create(match=match, player=other, team=self.home)
            PlayerStat.objects.create(
                match=match,
                player=other,
                team=self.home,
                event_type=self.goal,
                value=1,
            )

    def test_newest_first_with_limit_and_own_stats_only(self):
        self.lines()
        matches = player_recent_lines(self.scorer, self.player)
        self.assertEqual(len(matches), 5)
        self.assertGreater(matches[0].starts_at, matches[1].starts_at)
        self.assertTrue(
            all(s.player_id == self.scorer.pk for m in matches for s in m.player_line)
        )

    def test_query_count_is_fixed(self):
        self.lines()
        small = count_queries(
            lambda: list(player_recent_lines(self.scorer, self.player))
        )
        self.lines(prefix="more")
        self.assertEqual(
            count_queries(lambda: list(player_recent_lines(self.scorer, self.player))),
            small,
        )
