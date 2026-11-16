import importlib
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from .models import Sport
from .sport_defaults import DEFAULT_PERIODS, SPORT_PERIODS, default_periods

period_migration = importlib.import_module("teams.migrations.0014_sport_period_defaults")


def periods(name):
    sport = Sport.objects.get(name=name)
    return sport.period_count, sport.period_label


class SportDefaultsTests(SimpleTestCase):
    def test_migration_copy_matches_app_mapping(self):
        self.assertEqual(period_migration.PERIODS, SPORT_PERIODS)
        self.assertEqual(period_migration.DEFAULT, DEFAULT_PERIODS)

    def test_default_matches_model_fields(self):
        fields = Sport._meta
        self.assertEqual(
            (
                fields.get_field("period_count").default,
                fields.get_field("period_label").default,
            ),
            DEFAULT_PERIODS,
        )

    def test_known_names_ignore_case_and_spacing(self):
        self.assertEqual(default_periods("  FUTSAL "), (2, "Half"))
        self.assertEqual(default_periods("Ultimate   Frisbee"), (2, "Half"))
        self.assertEqual(default_periods("volleyball"), (5, "Set"))

    def test_unknown_or_blank_name_gets_default(self):
        self.assertEqual(default_periods("Cricket"), (4, "Q"))
        self.assertEqual(default_periods(""), (4, "Q"))


class SeedLeagueDataPeriodsTests(TestCase):
    EXPECTED = {
        "Basketball": (4, "Q"),
        "Cricket": (4, "Q"),
        "Flag football": (4, "Q"),
        "Futsal": (2, "Half"),
        "Pickleball": (4, "Q"),
        "Soccer": (2, "Half"),
        "Softball": (4, "Q"),
        "Ultimate frisbee": (2, "Half"),
        "Volleyball": (5, "Set"),
    }

    def test_fresh_database_gets_each_sports_periods(self):
        self.assertFalse(Sport.objects.exists())
        call_command("seed_league_data", stdout=StringIO())
        self.assertEqual(
            {s.name: (s.period_count, s.period_label) for s in Sport.objects.all()},
            self.EXPECTED,
        )

    def test_existing_sport_keeps_its_periods(self):
        Sport.objects.create(name="Soccer", period_count=3, period_label="Q")
        call_command("seed_league_data", stdout=StringIO())
        self.assertEqual(periods("Soccer"), (3, "Q"))
