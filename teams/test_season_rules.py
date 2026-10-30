from datetime import date

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from teams.season_rules import (
    can_transition,
    division_matches,
    season_allows,
    state_from_legacy_is_active,
    validate_season_dates,
    validate_transition,
)


class SeasonTransitionTests(SimpleTestCase):
    def test_allowed_transitions(self):
        for current, target in [
            ("draft", "open"),
            ("open", "draft"),
            ("open", "active"),
            ("active", "closed"),
        ]:
            with self.subTest(current=current, target=target):
                self.assertTrue(can_transition(current, target))

    def test_disallowed_transitions(self):
        for current, target in [
            ("draft", "active"),
            ("draft", "closed"),
            ("active", "open"),
            ("closed", "open"),
            ("closed", "draft"),
            ("open", "open"),
            ("archived", "open"),
            ("open", "archived"),
        ]:
            with self.subTest(current=current, target=target):
                self.assertFalse(can_transition(current, target))

    def test_validate_transition_raises_with_labels(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_transition("closed", "open")
        self.assertEqual(
            ctx.exception.messages, ["A season can't move from Closed to Open."]
        )
        self.assertIsNone(validate_transition("draft", "open"))


class SeasonAllowsTests(SimpleTestCase):
    def test_season_allows_matrix(self):
        expected = {
            "create_team": {
                "draft": False,
                "open": True,
                "active": False,
                "closed": False,
            },
            "request_free_agent": {
                "draft": False,
                "open": True,
                "active": True,
                "closed": False,
            },
            "match_free_agents": {
                "draft": False,
                "open": True,
                "active": True,
                "closed": False,
            },
        }
        for action, by_state in expected.items():
            for state, allowed in by_state.items():
                with self.subTest(state=state, action=action):
                    self.assertIs(season_allows(state, action), allowed)
        self.assertIs(season_allows("archived", "create_team"), False)


class SeasonDatesTests(SimpleTestCase):
    def test_validate_season_dates(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_season_dates(date(2026, 9, 2), date(2026, 9, 1))
        self.assertIn("end_date", ctx.exception.message_dict)
        self.assertIsNone(validate_season_dates(date(2026, 9, 1), date(2026, 9, 1)))
        self.assertIsNone(validate_season_dates(date(2026, 9, 1), None))


class LegacyAndDivisionTests(SimpleTestCase):
    def test_legacy_mapping(self):
        self.assertEqual(state_from_legacy_is_active(True), "open")
        self.assertEqual(state_from_legacy_is_active(False), "closed")

    def test_division_matches(self):
        self.assertTrue(division_matches(5, None))
        self.assertTrue(division_matches(None, None))
        self.assertTrue(division_matches(5, 5))
        self.assertFalse(division_matches(5, 6))
        self.assertFalse(division_matches(None, 6))
