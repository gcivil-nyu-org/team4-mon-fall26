import os
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role

from .management.commands.seed_league_data import SPORTS
from .models import Roster, Season, Sport, Team
from .season_rules import SeasonState


def seed(*args):
    out = StringIO()
    call_command("seed_league_data", *args, stdout=out)
    return out.getvalue()


def snapshot(model_or_queryset):
    queryset = getattr(model_or_queryset, "objects", model_or_queryset)
    return list(queryset.order_by("pk").values())


def open_season():
    return Season.objects.create(
        name="Fall 2026", start_date="2026-09-01", state=SeasonState.OPEN
    )


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


class SeedLeagueDataTests(TestCase):
    def test_creates_every_sport_once(self):
        seed()
        seed()
        self.assertEqual(
            sorted(Sport.objects.values_list("name", flat=True)), sorted(SPORTS)
        )

    def test_existing_sport_with_other_spelling_is_not_duplicated(self):
        Sport.objects.create(name="soccer")
        seed()
        self.assertEqual(Sport.objects.count(), len(SPORTS))
        self.assertTrue(Sport.objects.filter(name="soccer").exists())

    def test_no_season_without_the_flag(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEED_DEMO_SEASON", None)
            output = seed()
        self.assertFalse(Season.objects.exists())
        self.assertNotIn("retired", output)

    def test_demo_season_flag_creates_no_season(self):
        output = seed("--demo-season")
        self.assertFalse(Season.objects.exists())
        self.assertIn("--demo-season is retired and does nothing", output)
        self.assertEqual(Sport.objects.count(), len(SPORTS))

    def test_demo_season_variable_creates_no_season(self):
        with mock.patch.dict(os.environ, {"SEED_DEMO_SEASON": "1"}):
            output = seed()
        self.assertFalse(Season.objects.exists())
        self.assertIn("SEED_DEMO_SEASON is retired and does nothing", output)
        self.assertEqual(Sport.objects.count(), len(SPORTS))

    def test_existing_plain_season_with_teams_is_not_touched(self):
        season = Season.objects.create(
            name="Fall 2026",
            start_date="2026-09-01",
            end_date="2026-12-15",
            state=SeasonState.ACTIVE,
        )
        team = Team.objects.create(
            name="Violets",
            sport=Sport.objects.create(name="Soccer"),
            season=season,
            captain=make_user("cap"),
        )
        Roster.objects.create(team=team, player=team.captain)
        before = (snapshot(Season), snapshot(Team), snapshot(Roster))
        variables = {
            "SEED_DEMO_SEASON": "1",
            "SEED_DEMO_LEAGUE": "1",
            "DEMO_USERS_PASSWORD": "demo-pass-123",
        }
        with mock.patch.dict(os.environ, variables):
            seed("--demo-season")
            self.assertEqual((snapshot(Season), snapshot(Team)), before[:2])
            # The other seed commands, in deploy order.
            for command in (
                "seed_demo_users",
                "seed_semester_seasons",
                "seed_demo_league",
            ):
                call_command(command, stdout=StringIO())
        plain = Season.objects.filter(name="Fall 2026")
        self.assertEqual(snapshot(plain), before[0])
        self.assertEqual(snapshot(Team.objects.filter(season=season)), before[1])
        self.assertEqual(snapshot(Roster.objects.filter(team=team)), before[2])


class CreateTeamGuidanceTests(TestCase):
    def setUp(self):
        self.user = make_user("cap")
        self.client.force_login(self.user)
        self.url = reverse("teams:create")

    def test_player_is_told_no_sports_exist(self):
        response = self.client.get(self.url)
        self.assertContains(response, "No sports have been added yet")
        self.assertContains(response, "Ask a League Admin to add one.")

    def test_admin_gets_a_link_to_add_a_sport(self):
        assign_role(self.user, LEAGUE_ADMIN_ROLE)
        response = self.client.get(self.url)
        self.assertContains(response, reverse("teams:manage_sports"))

    def test_no_open_season_note(self):
        seed()
        response = self.client.get(self.url)
        self.assertNotContains(response, "No sports have been added yet")
        self.assertContains(response, "No season is open for registration")

    def test_no_notes_once_sports_and_an_open_season_exist(self):
        seed()
        open_season()
        response = self.client.get(self.url)
        self.assertNotContains(response, "No sports have been added yet")
        self.assertNotContains(response, "No season is open for registration")

    def test_seeded_data_lets_a_player_create_a_team(self):
        seed()
        open_season()
        response = self.client.post(
            self.url,
            {
                "name": "Violets",
                "sport": Sport.objects.get(name="Soccer").pk,
                "season": Season.objects.get().pk,
            },
        )
        team = Team.objects.get(name="Violets")
        self.assertRedirects(response, reverse("teams:detail", args=[team.pk]))
        self.assertEqual(team.captain, self.user)
