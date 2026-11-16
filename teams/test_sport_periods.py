import importlib

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from matches.tests import make_user

from .models import Sport

period_defaults = importlib.import_module("teams.migrations.0014_sport_period_defaults")


class SportPeriodModelTests(TestCase):
    def test_defaults(self):
        sport = Sport.objects.create(name="Rugby")
        self.assertEqual(sport.period_count, 4)
        self.assertEqual(sport.period_label, "Q")

    def test_period_name(self):
        sport = Sport(name="X", period_count=4, period_label="Q")
        self.assertEqual(
            [sport.period_name(n) for n in (1, 4, 5, 6)], ["Q1", "Q4", "OT1", "OT2"]
        )
        sport.period_label = "Half"
        sport.period_count = 2
        self.assertEqual(sport.period_name(2), "Half 2")
        self.assertEqual(sport.period_name(3), "OT1")

    def test_period_count_max_10(self):
        with self.assertRaises(ValidationError) as caught:
            Sport(name="Rugby", period_count=11).full_clean()
        self.assertIn("period_count", caught.exception.message_dict)

    def test_zero_periods_allowed(self):
        Sport(name="Tennis", period_count=0).full_clean()


class EditSportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin", admin=True)
        cls.player = make_user("player")
        cls.sport = Sport.objects.create(name="Soccer")
        cls.url = reverse("teams:edit_sport", args=[cls.sport.pk])

    def test_edit_sport_saves_periods(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.client.post(
            self.url, {"name": "Soccer", "period_count": 2, "period_label": "Half"}
        )
        self.assertRedirects(response, reverse("teams:manage_sports"))
        self.sport.refresh_from_db()
        self.assertEqual(
            (self.sport.period_count, self.sport.period_label), (2, "Half")
        )

    def test_edit_sport_shows_errors(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self.url, {"name": "Soccer", "period_count": 11, "period_label": "Q"}
        )
        self.assertEqual(response.status_code, 200)
        self.sport.refresh_from_db()
        self.assertEqual(self.sport.period_count, 4)

    def test_edit_sport_denies_casual_player(self):
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_manage_sports_links_edit(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("teams:manage_sports"))
        self.assertContains(response, reverse("teams:edit_sport", args=[self.sport.pk]))
        self.assertContains(response, "periods")

    def test_add_sport_without_period_fields_uses_defaults(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("teams:manage_sports"), {"name": "Rugby"})
        rugby = Sport.objects.get(name="Rugby")
        self.assertEqual((rugby.period_count, rugby.period_label), (4, "Q"))


class SportPeriodDefaultsMigrationTests(TestCase):
    """The data migration sets periods for known sports by name."""

    def run_forward(self):
        period_defaults.set_period_defaults(apps, None)

    def stored(self, name):
        sport = Sport.objects.get(name=name)
        return sport.period_count, sport.period_label

    def test_known_sports_get_their_periods(self):
        for name in (
            "Basketball",
            "soccer",
            "FUTSAL",
            "Volleyball",
            "Flag Football",
            "Ultimate",
        ):
            Sport.objects.create(name=name)
        Sport.objects.create(name="Tennis")
        self.run_forward()
        self.assertEqual(self.stored("Basketball"), (4, "Q"))
        self.assertEqual(self.stored("soccer"), (2, "Half"))
        self.assertEqual(self.stored("FUTSAL"), (2, "Half"))
        self.assertEqual(self.stored("Volleyball"), (5, "Set"))
        self.assertEqual(self.stored("Flag Football"), (4, "Q"))
        self.assertEqual(self.stored("Ultimate"), (2, "Half"))
        self.assertEqual(self.stored("Tennis"), (4, "Q"))

    def test_reverse_restores_defaults(self):
        Sport.objects.create(name="Soccer")
        Sport.objects.create(name="Tennis", period_count=0, period_label="Set")
        self.run_forward()
        period_defaults.clear_period_defaults(apps, None)
        self.assertEqual(self.stored("Soccer"), (4, "Q"))
        # Sports the migration didn't set keep their values.
        self.assertEqual(self.stored("Tennis"), (0, "Set"))
