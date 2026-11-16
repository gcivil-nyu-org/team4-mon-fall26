"""Pure-function tests for the match page sections (#255)."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from .standings import positions, rank_rows


def team(pk, name, division=None):
    return SimpleNamespace(
        pk=pk,
        name=name,
        division_id=division.pk if division else None,
        division=division,
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
