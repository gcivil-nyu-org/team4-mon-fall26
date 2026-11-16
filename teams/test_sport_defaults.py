import importlib
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from matches.models import MatchPeriodScore
from matches.tests import MatchFixtures, make_user

from .forms import SportForm
from .models import Sport
from .sport_defaults import DEFAULT_PERIODS, SPORT_PERIODS, default_periods

period_migration = importlib.import_module(
    "teams.migrations.0014_sport_period_defaults"
)


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


class NewSportPeriodsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin", admin=True)
        cls.root = get_user_model().objects.create_superuser(
            username="root", email="root@nyu.edu", password="pw12345!"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_new_form_shows_blank_period_fields(self):
        form = SportForm()
        self.assertIsNone(form["period_count"].value())
        self.assertIsNone(form["period_label"].value())

    def test_explicit_initial_is_kept(self):
        form = SportForm(initial={"period_count": 2})
        self.assertEqual(form["period_count"].value(), 2)
        self.assertIsNone(form["period_label"].value())

    def test_edit_form_shows_stored_periods(self):
        sport = Sport.objects.create(name="Soccer", period_count=2, period_label="Half")
        form = SportForm(instance=sport)
        self.assertEqual(
            (form["period_count"].value(), form["period_label"].value()), (2, "Half")
        )

    def test_manage_page_blank_periods_use_sport_defaults(self):
        self.client.post(reverse("teams:manage_sports"), {"name": "  FUTSAL "})
        self.assertEqual(periods("FUTSAL"), (2, "Half"))

    def test_manage_page_typed_periods_win(self):
        self.client.post(
            reverse("teams:manage_sports"),
            {"name": "Soccer", "period_count": 4, "period_label": "Q"},
        )
        self.assertEqual(periods("Soccer"), (4, "Q"))

    def test_each_blank_field_is_filled_on_its_own(self):
        self.client.post(
            reverse("teams:manage_sports"),
            {"name": "Soccer", "period_count": 3, "period_label": ""},
        )
        self.assertEqual(periods("Soccer"), (3, "Half"))

    def test_unknown_sport_gets_model_default(self):
        self.client.post(reverse("teams:manage_sports"), {"name": "Rugby"})
        self.assertEqual(periods("Rugby"), (4, "Q"))

    def test_blank_name_shows_error(self):
        response = self.client.post(reverse("teams:manage_sports"), {"name": ""})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["name"])
        self.assertFalse(Sport.objects.exists())

    def test_edit_with_blank_periods_keeps_stored_values(self):
        sport = Sport.objects.create(name="Soccer")
        self.client.post(
            reverse("teams:edit_sport", args=[sport.pk]),
            {"name": "Soccer", "period_count": "", "period_label": ""},
        )
        self.assertEqual(periods("Soccer"), (4, "Q"))

    def test_admin_add_blank_periods_use_sport_defaults(self):
        self.client.force_login(self.root)
        self.client.post(reverse("admin:teams_sport_add"), {"name": "Volleyball"})
        self.assertEqual(periods("Volleyball"), (5, "Set"))


class FixSportPeriodsTests(MatchFixtures):
    # Not "run": unittest.TestCase.run runs the test itself.
    def run_command(self, *args):
        out = StringIO()
        call_command("fix_sport_periods", *args, stdout=out)
        return out.getvalue()

    def test_fixes_default_valued_known_sport(self):
        futsal = Sport.objects.create(name="Futsal")
        output = self.run_command()
        futsal.refresh_from_db()
        self.assertEqual((futsal.period_count, futsal.period_label), (2, "Half"))
        self.assertIn("Futsal: fixed to 2 Half.", output)

    def test_keeps_custom_values_unknown_sports_and_basketball(self):
        Sport.objects.create(name="Volleyball", period_count=3, period_label="Set")
        Sport.objects.create(name="Rugby")
        output = self.run_command()
        self.assertEqual(periods("Volleyball"), (3, "Set"))
        self.assertEqual(periods("Rugby"), (4, "Q"))
        self.assertEqual(periods("Basketball"), (4, "Q"))
        self.assertIn("Volleyball: kept (3 Set, set by an admin).", output)
        self.assertNotIn("Rugby", output)
        self.assertNotIn("Basketball", output)
        self.assertIn("Fixed 1, kept 1, skipped 0.", output)

    def test_skips_sport_with_period_scores(self):
        match = self.build()
        match.save()
        MatchPeriodScore.objects.create(
            match=match, period=1, home_points=1, away_points=0
        )
        output = self.run_command()
        self.assertEqual(periods("Soccer"), (4, "Q"))
        self.assertIn("Soccer: skipped (period scores stored).", output)
        self.assertIn("Fixed 0, kept 0, skipped 1.", output)

    def test_dry_run_writes_nothing(self):
        Sport.objects.create(name="Futsal")
        output = self.run_command("--dry-run")
        self.assertEqual(periods("Futsal"), (4, "Q"))
        self.assertEqual(periods("Soccer"), (4, "Q"))
        self.assertIn("Futsal: would fix to 2 Half.", output)
        # self.soccer is also a 4 Q Soccer with no period scores, so 2 fixes.
        self.assertIn("Dry run: Fixed 2, kept 0, skipped 0.", output)
