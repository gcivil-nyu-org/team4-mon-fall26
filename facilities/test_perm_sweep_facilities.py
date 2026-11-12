"""Permission sweep (#153): every League Admin page in facilities/.

Anonymous visitors bounce to login (302), signed-in Casual Players get
403, and League Admins get 200.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.roles import CASUAL_PLAYER_ROLE, LEAGUE_ADMIN_ROLE, assign_role
from facilities.models import Facility


def make_user(email, role=None):
    user = get_user_model().objects.create_user(
        username=email, email=email, password="testpass123"
    )
    if role is not None:
        assign_role(user, role)
    return user


class FacilitiesLeagueAdminSweepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.facility = Facility.objects.create(
            name="Palladium Gym", source=Facility.Source.NYU
        )

    def setUp(self):
        self.player = make_user("player@nyu.edu", CASUAL_PLAYER_ROLE)
        self.admin = make_user("admin@nyu.edu", LEAGUE_ADMIN_ROLE)

    def get_urls(self):
        return [
            reverse("facilities:manage"),
            reverse("facilities:create"),
            reverse("facilities:edit", kwargs={"pk": self.facility.pk}),
        ]

    def test_anonymous_is_sent_to_login(self):
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_casual_player_is_denied(self):
        self.client.force_login(self.player)
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_league_admin_gets_through(self):
        self.client.force_login(self.admin)
        for url in self.get_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
