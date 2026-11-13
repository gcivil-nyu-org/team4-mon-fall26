"""Permission sweep (#153): every League Admin page in matches/.

Anonymous visitors bounce to login (302), signed-in Casual Players get
403, and League Admins get through (200 for pages, 302 for the cancel POST).
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import CASUAL_PLAYER_ROLE, LEAGUE_ADMIN_ROLE, assign_role
from facilities.models import Facility
from matches.models import Match
from teams.models import Season, Sport, Team


def make_user(email, role=None):
    user = get_user_model().objects.create_user(
        username=email, email=email, password="testpass123"
    )
    if role is not None:
        assign_role(user, role)
    return user


class MatchesLeagueAdminSweepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.captain = make_user("captain@nyu.edu")
        cls.season = Season.objects.create(
            name="Fall 2026", start_date=date(2026, 9, 1), state="open"
        )
        sport = Sport.objects.create(name="Soccer")
        facility = Facility.objects.create(
            name="Palladium Gym", source=Facility.Source.NYU
        )
        home = Team.objects.create(
            name="Violets", sport=sport, season=cls.season, captain=cls.captain
        )
        away = Team.objects.create(
            name="Rivals", sport=sport, season=cls.season, captain=cls.captain
        )
        now = timezone.now()
        cls.match = Match.objects.create(
            season=cls.season,
            home_team=home,
            away_team=away,
            facility=facility,
            starts_at=now,
            ends_at=now + timedelta(hours=2),
        )

    def setUp(self):
        self.player = make_user("player@nyu.edu", CASUAL_PLAYER_ROLE)
        self.admin = make_user("admin@nyu.edu", LEAGUE_ADMIN_ROLE)

    def get_urls(self):
        return [
            reverse("matches:manage"),
            reverse("matches:create"),
            reverse("matches:edit", kwargs={"pk": self.match.pk}),
        ]

    def cancel_url(self):
        return reverse("matches:cancel", kwargs={"pk": self.match.pk})

    def test_anonymous_is_sent_to_login(self):
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(self.cancel_url()).status_code, 302)

    def test_casual_player_is_denied(self):
        self.client.force_login(self.player)
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(self.cancel_url()).status_code, 403)

    def test_league_admin_gets_through(self):
        self.client.force_login(self.admin)
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(self.cancel_url()).status_code, 302)
