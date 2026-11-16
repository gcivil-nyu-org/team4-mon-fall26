"""Pure-function tests for the match page sections (#255)."""

import datetime
from types import SimpleNamespace

from django.test import SimpleTestCase

from .match_context import Result, head_to_head, standings_movement, team_context
from .standings import positions, rank_rows
from .stats import (
    Leader,
    SheetRow,
    TeamSheet,
    comparison_rows,
    ordered_event_types,
    team_totals,
    top_performers,
)


def team(pk, name, division=None):
    return SimpleNamespace(
        pk=pk,
        name=name,
        division_id=division.pk if division else None,
        division=division,
    )


def when(day, hour=18):
    return datetime.datetime(2026, 10, day, hour, tzinfo=datetime.timezone.utc)


def result(pk, day, home, away, home_score, away_score, hour=18):
    return Result(pk, when(day, hour), home.pk, away.pk, home_score, away_score)


def match(pk, day, home, away, has_result=True, is_cancelled=False, hour=18):
    return SimpleNamespace(
        pk=pk,
        starts_at=when(day, hour),
        home_team_id=home.pk,
        away_team_id=away.pk,
        home_team=home,
        away_team=away,
        has_result=has_result,
        is_cancelled=is_cancelled,
    )


class PositionsTests(SimpleTestCase):
    def test_positions_season_and_division(self):
        east = SimpleNamespace(pk=1, name="East")
        a, b, c = team(1, "A", east), team(2, "B"), team(3, "C", east)
        rows = rank_rows([a, b, c], [(3, 2, 2, 0), (3, 1, 1, 0)])  # C beats B and A
        got = positions(rows)
        # C 6 pts; A and B 0 pts, split by name.
        self.assertEqual([got[t.pk]["position"] for t in (c, a, b)], [1, 2, 3])
        self.assertEqual(got[1]["of"], 3)
        self.assertEqual((got[3]["division_position"], got[3]["division_of"]), (1, 2))
        self.assertEqual((got[1]["division_position"], got[1]["division_of"]), (2, 2))
        self.assertIsNone(got[2]["division_position"])
        self.assertIsNone(got[2]["division_of"])
        self.assertIs(got[3]["row"], rows[0])

    def test_positions_empty(self):
        self.assertEqual(positions([]), {})


class TeamContextTests(SimpleTestCase):
    def setUp(self):
        self.a, self.b, self.c = team(1, "A"), team(2, "B"), team(3, "C")
        self.teams = [self.a, self.b, self.c]

    def test_form_newest_first_capped_and_marks_this_match(self):
        # Seven results for team A; this match is the 4th.
        results = [result(pk, pk, self.a, self.b, 1, 0) for pk in range(1, 8)]
        this = match(4, 4, self.a, self.b)
        ctx = team_context(this, self.teams, results)
        self.assertEqual(len(ctx[0].form), 5)
        self.assertEqual([f.match_pk for f in ctx[0].form], [7, 6, 5, 4, 3])
        self.assertTrue(ctx[0].form[3].is_this_match)
        self.assertFalse(ctx[0].form[0].is_this_match)
        self.assertEqual(ctx[0].form[0].opponent, self.b)
        self.assertEqual(ctx[1].team, self.b)

    def test_form_letters_from_each_side(self):
        results = [
            result(1, 1, self.a, self.b, 2, 1),
            result(2, 2, self.a, self.b, 0, 0),
        ]
        ctx = team_context(match(3, 3, self.a, self.b, False), self.teams, results)
        self.assertEqual([f.letter for f in ctx[0].form], ["D", "W"])
        self.assertEqual([f.letter for f in ctx[1].form], ["D", "L"])
        self.assertEqual((ctx[1].form[1].scored, ctx[1].form[1].conceded), (1, 2))
        self.assertEqual(ctx[1].form[1].opponent, self.a)

    def test_record_and_position(self):
        results = [
            result(1, 1, self.a, self.b, 2, 1),
            result(2, 2, self.c, self.a, 0, 3),
            result(3, 3, self.b, self.c, 1, 1),
        ]
        ctx = team_context(match(4, 4, self.a, self.b, False), self.teams, results)
        self.assertEqual((ctx[0].row["won"], ctx[0].row["points"]), (2, 6))
        self.assertEqual(ctx[0].standing["position"], 1)
        self.assertEqual(ctx[1].standing["position"], 2)

    def test_no_results_gives_zero_played(self):
        ctx = team_context(match(1, 1, self.a, self.b, False), self.teams, [])
        self.assertEqual(ctx[0].row["played"], 0)
        self.assertEqual(ctx[0].form, [])

    def test_form_skips_unknown_opponent(self):
        stranger = team(9, "Z")
        results = [result(1, 1, self.a, stranger, 1, 0)]
        ctx = team_context(match(2, 2, self.a, self.b, False), self.teams, results)
        self.assertEqual(ctx[0].form, [])

    def test_head_to_head_counts_both_orientations(self):
        # A 2-1 B (A home), B 1-1 A, B 3-0 A, A 1-0 C (skipped)
        results = [
            result(1, 1, self.a, self.b, 2, 1),
            result(2, 2, self.b, self.a, 1, 1),
            result(3, 3, self.b, self.a, 3, 0),
            result(4, 4, self.a, self.c, 1, 0),
        ]
        h2h = head_to_head(match(5, 5, self.a, self.b, False), results)
        self.assertEqual((h2h.home_wins, h2h.draws, h2h.away_wins), (1, 1, 1))
        self.assertEqual([r.pk for r in h2h.meetings], [3, 2, 1])

    def test_head_to_head_empty(self):
        this = match(1, 1, self.a, self.b, False)
        self.assertEqual(head_to_head(this, []).meetings, [])


class MovementTests(SimpleTestCase):
    def setUp(self):
        # "Zed" sorts last by name, so name tie-breaks never favour it.
        self.zed, self.b, self.c = team(1, "Zed"), team(2, "B"), team(3, "C")
        self.d, self.e = team(4, "D"), team(5, "E")
        self.teams = [self.zed, self.b, self.c, self.d, self.e]
        # Before: C 3, E 3, B 1, D 1, Zed 0 (played 1). Zed 5th, B 3rd.
        self.earlier = [
            result(1, 1, self.c, self.zed, 1, 0),
            result(2, 2, self.e, self.d, 1, 0),
            result(3, 3, self.b, self.d, 0, 0),
        ]
        self.this = match(10, 5, self.zed, self.b)

    def movement(self, home_score, away_score, extra=()):
        this_result = result(10, 5, self.zed, self.b, home_score, away_score)
        results = sorted(
            [*self.earlier, this_result, *extra], key=lambda r: (r.starts_at, r.pk)
        )
        return standings_movement(self.this, self.teams, results)

    def test_win_moves_up(self):
        home = self.movement(2, 1)[0]
        self.assertEqual(home.team, self.zed)
        self.assertEqual((home.direction, home.change), ("up", 2))
        self.assertEqual((home.before_position, home.after_position), (5, 3))
        self.assertEqual((home.of, home.table_label), (5, None))
        self.assertEqual(home.points_change, 3)

    def test_loss_moves_down(self):
        away = self.movement(2, 1)[1]
        self.assertEqual((away.direction, away.change, away.places), ("down", -1, 1))
        self.assertEqual((away.before_position, away.after_position), (3, 4))
        self.assertEqual(away.after_points, away.before_points)

    def test_draw_same_position(self):
        home = self.movement(1, 1)[0]
        self.assertEqual((home.direction, home.change), ("same", 0))
        self.assertEqual(home.after_points - home.before_points, 1)

    def test_same_start_lower_pk_is_before(self):
        other = result(9, 5, self.zed, self.d, 1, 0)
        home = self.movement(2, 1, [other])[0]
        self.assertEqual((home.before_points, home.after_points), (3, 6))

    def test_same_start_higher_pk_is_not_before(self):
        other = result(11, 5, self.zed, self.d, 1, 0)
        home = self.movement(2, 1, [other])[0]
        self.assertEqual((home.before_points, home.after_points), (0, 3))

    def test_later_matches_ignored(self):
        later = result(20, 9, self.d, self.zed, 5, 0)
        self.assertEqual(self.movement(2, 1), self.movement(2, 1, [later]))

    def test_first_result(self):
        a, b = team(1, "A"), team(2, "B")
        first_match = match(1, 1, a, b)
        m = standings_movement(first_match, [a, b], [result(1, 1, a, b, 1, 0)])
        self.assertEqual([x.direction for x in m], ["first", "first"])
        self.assertIsNone(m[0].before_position)
        self.assertEqual(m[0].change, 0)
        self.assertEqual((m[0].after_position, m[0].after_points), (1, 3))

    def test_division_table_for_division_team(self):
        east = SimpleNamespace(pk=1, name="East")
        home, x, y = team(1, "H", east), team(2, "X", east), team(3, "Y", east)
        away, q = team(4, "Aw"), team(5, "Q")
        this = match(1, 1, home, away)
        teams = [home, x, y, away, q]
        m = standings_movement(this, teams, [result(1, 1, home, away, 1, 0)])
        self.assertEqual((m[0].table_label, m[0].of), ("East", 3))
        self.assertEqual(m[0].after_position, 1)
        self.assertEqual((m[1].table_label, m[1].of), (None, 5))

    def test_cross_division_each_own_table(self):
        east = SimpleNamespace(pk=1, name="East")
        west = SimpleNamespace(pk=2, name="West")
        home, x = team(1, "H", east), team(2, "X", east)
        away, w, v = team(3, "Aw", west), team(4, "W", west), team(5, "V", west)
        earlier = result(1, 1, w, v, 1, 0)
        this = match(2, 2, home, away)
        teams = [home, x, away, w, v]
        m = standings_movement(this, teams, [earlier, result(2, 2, home, away, 0, 1)])
        self.assertEqual((m[0].table_label, m[0].of), ("East", 2))
        self.assertEqual((m[1].table_label, m[1].of), ("West", 3))
        self.assertEqual(m[1].after_position, 1)

    def test_none_without_result_or_cancelled(self):
        unscored = match(10, 5, self.zed, self.b, has_result=False)
        cancelled = match(10, 5, self.zed, self.b, is_cancelled=True)
        self.assertIsNone(standings_movement(unscored, self.teams, self.earlier))
        self.assertIsNone(standings_movement(cancelled, self.teams, self.earlier))


def person(pk, first="", last=""):
    full = f"{first} {last}".strip()
    return SimpleNamespace(
        pk=pk, first_name=first, last_name=last, get_full_name=lambda: full
    )


def stat_type(pk, name):
    return SimpleNamespace(pk=pk, name=name)


class TopPerformerTests(SimpleTestCase):
    def setUp(self):
        self.assist = stat_type(1, "Assist")
        self.points = stat_type(2, "Points")
        self.rebound = stat_type(3, "Rebound")
        self.steal = stat_type(4, "Steal")
        # The match page loads event types by name.
        self.types = [self.assist, self.points, self.rebound, self.steal]
        self.kim = person(1, "Sam", "Kim")
        self.lee = person(2, "Alex", "Lee")
        self.nameless = person(3)
        self.home, self.away = team(1, "Home"), team(2, "Away")

    def sheet(self, team_, *rows):
        return TeamSheet(team_, list(rows))

    def row(self, player, on_roster=True, **stats):
        by_name = {t.name: t.pk for t in self.types}
        values = {by_name[name.capitalize()]: value for name, value in stats.items()}
        return SheetRow(player, on_roster, True, values)

    def test_ordered_event_types(self):
        self.assertEqual(
            ordered_event_types(self.types, self.points),
            [self.points, self.assist, self.rebound, self.steal],
        )
        self.assertEqual(ordered_event_types(self.types, None), self.types)
        other = stat_type(9, "Kills")
        self.assertEqual(ordered_event_types(self.types, other), self.types)

    def test_scoring_type_first_and_capped_at_three(self):
        sheets = [
            self.sheet(
                self.home,
                self.row(self.lee, points=24, assist=3, rebound=8, steal=2),
            ),
            self.sheet(self.away),
        ]
        tp = top_performers(sheets, self.types, self.points)
        self.assertEqual(
            [leader.event_type for leader in tp[0].leaders],
            [self.points, self.assist, self.rebound],
        )
        self.assertEqual(tp[0].team, self.home)
        self.assertEqual(tp[1].leaders, [])

    def test_tie_goes_by_name_and_named_first(self):
        sheets = [
            self.sheet(
                self.home,
                self.row(self.nameless, points=5),
                self.row(self.lee, points=5),
                self.row(self.kim, points=5),
            )
        ]
        leader = top_performers(sheets, self.types, self.points)[0].leaders[0]
        self.assertEqual(leader.player, self.lee)  # "Alex Lee" before "Sam Kim".
        self.assertEqual(leader.value, 5)

    def test_zero_never_leads(self):
        sheets = [self.sheet(self.home, self.row(self.lee, points=4, rebound=0))]
        tp = top_performers(sheets, self.types, self.points)
        self.assertEqual([leader.event_type for leader in tp[0].leaders], [self.points])

    def test_player_who_left_can_lead(self):
        sheets = [
            self.sheet(
                self.home,
                self.row(self.kim, points=10),
                self.row(self.lee, on_roster=False, points=30),
            )
        ]
        tp = top_performers(sheets, self.types, self.points)
        self.assertEqual(tp[0].leaders[0].player, self.lee)

    def test_no_scoring_type_orders_by_name(self):
        sheets = [self.sheet(self.home, self.row(self.lee, points=4, assist=1))]
        tp = top_performers(sheets, self.types, None)
        self.assertEqual(
            [leader.event_type for leader in tp[0].leaders], [self.assist, self.points]
        )

    def test_no_event_types_no_leaders(self):
        sheets = [self.sheet(self.home, self.row(self.lee, points=4))]
        self.assertEqual(top_performers(sheets, [], None)[0].leaders, [])

    def test_short_name(self):
        self.assertEqual(Leader(self.lee, 24, self.points).short_name, "Lee")
        self.assertEqual(
            Leader(self.nameless, 1, self.points).short_name, "PlayNYU player"
        )
        first_only = person(4, "Mo")
        self.assertEqual(Leader(first_only, 1, self.points).short_name, "Mo")

    def test_totals_include_leavers(self):
        sheet = self.sheet(
            self.home,
            self.row(self.kim, points=1, assist=1),
            self.row(self.lee, on_roster=False, points=2),
        )
        self.assertEqual(team_totals(sheet, [self.points, self.assist]), [3, 1])

    def test_comparison_skips_zero_rows_and_rounds(self):
        rows = comparison_rows([self.assist, self.points], [1, 0], [2, 0], self.points)
        self.assertEqual([r.event_type for r in rows], [self.assist])
        self.assertEqual((rows[0].home, rows[0].away), (1, 2))
        self.assertEqual((rows[0].home_pct, rows[0].away_pct), (33, 67))

    def test_comparison_scoring_first(self):
        rows = comparison_rows([self.assist, self.points], [1, 3], [0, 1], self.points)
        self.assertEqual([r.event_type for r in rows], [self.points, self.assist])
        self.assertEqual((rows[1].home_pct, rows[1].away_pct), (100, 0))
