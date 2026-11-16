"""Pure-function tests for the match page sections (#255)."""

import datetime
from types import SimpleNamespace

from django.test import SimpleTestCase

from .match_context import Result, head_to_head, team_context
from .standings import positions, rank_rows


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
