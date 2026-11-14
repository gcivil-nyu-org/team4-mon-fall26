import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .default_seasons import (
    DEFAULT_DIVISIONS,
    created_seasons_message,
    ensure_default_seasons,
)
from .models import Division, Season, Sport
from .season_rules import SeasonState
from .semesters import current_semester, next_semester


def expected_semesters():
    current = current_semester(datetime.date.today())
    return current, next_semester(current)


class EnsureDefaultSeasonsTests(TestCase):
    def test_creates_open_and_draft_seasons(self):
        sport = Sport.objects.create(name="Basketball")

        seasons = ensure_default_seasons(sport, datetime.date(2026, 11, 13))

        self.assertEqual(
            [(s.name, s.term, s.state) for s in seasons],
            [
                ("Fall 2026 Basketball", "2026-fall", SeasonState.OPEN),
                ("Spring 2027 Basketball", "2027-spring", SeasonState.DRAFT),
            ],
        )
        for season in seasons:
            self.assertEqual(
                sorted(season.divisions.values_list("name", flat=True)),
                sorted(DEFAULT_DIVISIONS),
            )

    def test_second_call_creates_nothing(self):
        sport = Sport.objects.create(name="Basketball")
        today = datetime.date(2026, 11, 13)
        ensure_default_seasons(sport, today)

        self.assertEqual(ensure_default_seasons(sport, today), [])
        self.assertEqual(Season.objects.count(), 2)

    def test_defaults_to_today(self):
        sport = Sport.objects.create(name="Basketball")
        current, upcoming = expected_semesters()

        seasons = ensure_default_seasons(sport)

        self.assertEqual([s.term for s in seasons], [current.term, upcoming.term])

    def test_message_names_seasons(self):
        sport = Sport.objects.create(name="Basketball")
        seasons = ensure_default_seasons(sport, datetime.date(2026, 11, 13))

        self.assertEqual(
            created_seasons_message(seasons),
            "Sport added with Fall 2026 Basketball and Spring 2027 Basketball seasons.",
        )
        self.assertEqual(
            created_seasons_message(seasons[:1]),
            "Sport added with Fall 2026 Basketball season.",
        )
        self.assertEqual(created_seasons_message([]), "Sport added.")


class ManageSportsCreatesSeasonsTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="sports_admin", email="sports_admin@nyu.edu", password="pw12345!"
        )
        group, _ = Group.objects.get_or_create(name="League Admin")
        self.admin.groups.add(group)
        self.client.force_login(self.admin)

    def test_adding_sport_creates_seasons_and_names_them(self):
        current, upcoming = expected_semesters()

        response = self.client.post(
            reverse("teams:manage_sports"), {"name": "Volleyball"}, follow=True
        )

        sport = Sport.objects.get(name="Volleyball")
        seasons = Season.objects.filter(sport=sport).order_by("start_date")
        self.assertEqual(
            [(s.term, s.state) for s in seasons],
            [(current.term, SeasonState.OPEN), (upcoming.term, SeasonState.DRAFT)],
        )
        self.assertEqual(
            Division.objects.filter(season__sport=sport).count(),
            2 * len(DEFAULT_DIVISIONS),
        )
        self.assertContains(
            response,
            f"Sport added with {current.label} Volleyball and "
            f"{upcoming.label} Volleyball seasons.",
        )

    def test_invalid_sport_creates_no_seasons(self):
        self.client.post(reverse("teams:manage_sports"), {"name": ""})

        self.assertEqual(Season.objects.count(), 0)


class SportAdminCreatesSeasonsTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="root", email="root@nyu.edu", password="pw12345!"
        )
        self.client.force_login(self.superuser)

    def test_admin_add_creates_seasons(self):
        current, upcoming = expected_semesters()

        response = self.client.post(
            reverse("admin:teams_sport_add"), {"name": "Volleyball"}, follow=True
        )

        sport = Sport.objects.get(name="Volleyball")
        self.assertEqual(
            sorted(Season.objects.filter(sport=sport).values_list("term", flat=True)),
            sorted([current.term, upcoming.term]),
        )
        self.assertContains(response, f"{current.label} Volleyball")

    def test_admin_change_creates_no_seasons(self):
        sport = Sport.objects.create(name="Volleyball")

        self.client.post(
            reverse("admin:teams_sport_change", args=[sport.pk]), {"name": "Beach"}
        )

        sport.refresh_from_db()
        self.assertEqual(sport.name, "Beach")
        self.assertEqual(Season.objects.count(), 0)
