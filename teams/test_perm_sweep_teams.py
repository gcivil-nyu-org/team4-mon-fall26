"""Permission sweep (#153): every League Admin page in teams/.

Anonymous visitors bounce to login (302), signed-in Casual Players get
403, and League Admins get through (200 for pages, 302 for POST actions).
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.roles import CASUAL_PLAYER_ROLE, LEAGUE_ADMIN_ROLE, assign_role
from teams.models import Season


def make_user(email, role=None):
    user = get_user_model().objects.create_user(
        username=email, email=email, password="testpass123"
    )
    if role is not None:
        assign_role(user, role)
    return user


class TeamsLeagueAdminSweepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.open_season = Season.objects.create(
            name="Fall 2026", start_date=date(2026, 9, 1), state="open"
        )
        cls.draft_season = Season.objects.create(
            name="Spring 2027", start_date=date(2027, 1, 20), state="draft"
        )

    def setUp(self):
        self.player = make_user("player@nyu.edu", CASUAL_PLAYER_ROLE)
        self.admin = make_user("admin@nyu.edu", LEAGUE_ADMIN_ROLE)

    def get_urls(self):
        season = self.open_season
        return [
            reverse("teams:league_setup"),
            reverse("teams:manage_sports"),
            reverse("teams:manage_event_types"),
            reverse("teams:manage_seasons"),
            reverse("teams:create_season"),
            reverse("teams:edit_season", kwargs={"pk": season.pk}),
            reverse("teams:manage_divisions"),
            reverse("teams:manage_season_divisions", kwargs={"season_pk": season.pk}),
            reverse("teams:manage_free_agents"),
            reverse("teams:manage_season_free_agents", kwargs={"season_pk": season.pk}),
        ]

    def post_urls(self):
        return [
            (
                reverse(
                    "teams:match_free_agents",
                    kwargs={"season_pk": self.open_season.pk},
                ),
                {},
            ),
            (
                reverse(
                    "teams:change_season_state",
                    kwargs={"pk": self.draft_season.pk},
                ),
                {"state": "open"},
            ),
        ]

    def test_anonymous_is_sent_to_login(self):
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
        for url, data in self.post_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 302)

    def test_casual_player_is_denied(self):
        self.client.force_login(self.player)
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        for url, data in self.post_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)

    def test_league_admin_gets_through(self):
        self.client.force_login(self.admin)
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        for url, data in self.post_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 302)
