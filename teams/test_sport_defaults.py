import importlib

from django.test import SimpleTestCase

from .models import Sport
from .sport_defaults import DEFAULT_PERIODS, SPORT_PERIODS, default_periods

period_migration = importlib.import_module("teams.migrations.0014_sport_period_defaults")


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
