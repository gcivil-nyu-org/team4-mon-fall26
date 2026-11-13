"""Sport rules for per-sport seasons. Design: docs/superpowers/specs/2026-11-13-semester-seasons-design.md."""

import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role

from .forms import FreeAgentRequestForm, SeasonForm, TeamCreateForm
from .models import FreeAgentRequest, Season, Sport, Team
from .season_rules import SeasonState

START = datetime.date(2026, 9, 1)


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


class SportRuleBase(TestCase):
    def setUp(self):
        self.basketball = Sport.objects.create(name="Basketball")
        self.soccer = Sport.objects.create(name="Soccer")
        self.season = Season.objects.create(
            name="Fall 2026 Basketball",
            start_date=START,
            state=SeasonState.OPEN,
            sport=self.basketball,
        )
        self.any_season = Season.objects.create(
            name="Custom League", start_date=START, state=SeasonState.OPEN
        )
        self.user = make_user("player1")


class TeamSportRuleTests(SportRuleBase):
    def team_form(self, season, sport, name="Violets"):
        return TeamCreateForm(
            {"name": name, "sport": sport.pk, "season": season.pk},
            user=self.user,
        )

    def test_model_refuses_team_of_another_sport(self):
        team = Team(
            name="Violets", sport=self.soccer, season=self.season, captain=self.user
        )
        with self.assertRaises(ValidationError) as caught:
            team.save()
        self.assertEqual(
            caught.exception.message_dict["sport"],
            ["Teams in Fall 2026 Basketball must play Basketball."],
        )
        self.assertFalse(Team.objects.exists())

    def test_model_refuses_moving_team_to_season_of_another_sport(self):
        team = Team.objects.create(
            name="Violets", sport=self.soccer, season=self.any_season, captain=self.user
        )
        team.season = self.season
        with self.assertRaises(ValidationError) as caught:
            team.save()
        self.assertIn("sport", caught.exception.message_dict)

    def test_model_allows_matching_sport(self):
        Team.objects.create(
            name="Violets", sport=self.basketball, season=self.season, captain=self.user
        )
        self.assertEqual(Team.objects.get().season, self.season)

    def test_season_with_no_sport_allows_any_sport(self):
        for sport in (self.basketball, self.soccer):
            with self.subTest(sport=sport.name):
                Team.objects.create(
                    name=f"{sport.name} team",
                    sport=sport,
                    season=self.any_season,
                    captain=self.user,
                )
        self.assertEqual(self.any_season.teams.count(), 2)

    def test_form_replaces_another_sport_with_the_season_sport(self):
        # The season fixes the sport (#191), so a stale choice gives no error.
        form = self.team_form(self.season, self.soccer)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sport"], self.basketball)

    def test_form_allows_matching_sport(self):
        form = self.team_form(self.season, self.basketball)
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_allows_any_sport_in_season_with_no_sport(self):
        form = self.team_form(self.any_season, self.soccer)
        self.assertTrue(form.is_valid(), form.errors)

    def test_create_view_saves_the_season_sport(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("teams:create"),
            {"name": "Violets", "sport": self.soccer.pk, "season": self.season.pk},
        )
        team = Team.objects.get()
        self.assertRedirects(response, reverse("teams:detail", args=[team.pk]))
        self.assertEqual(team.sport, self.basketball)


class FreeAgentSportRuleTests(SportRuleBase):
    def request_form(self, season, sport):
        return FreeAgentRequestForm(
            {"season": season.pk, "sport": sport.pk}, user=self.user
        )

    def test_model_refuses_request_of_another_sport(self):
        request = FreeAgentRequest(
            player=self.user, season=self.season, sport=self.soccer
        )
        with self.assertRaises(ValidationError) as caught:
            request.save()
        self.assertIn("sport", caught.exception.message_dict)
        self.assertFalse(FreeAgentRequest.objects.exists())

    def test_model_allows_matching_sport_and_any_sport_season(self):
        FreeAgentRequest.objects.create(
            player=self.user, season=self.season, sport=self.basketball
        )
        FreeAgentRequest.objects.create(
            player=self.user, season=self.any_season, sport=self.soccer
        )
        self.assertEqual(FreeAgentRequest.objects.count(), 2)

    def test_form_replaces_another_sport_with_the_season_sport(self):
        form = self.request_form(self.season, self.soccer)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sport"], self.basketball)

    def test_form_allows_matching_sport(self):
        self.assertTrue(self.request_form(self.season, self.basketball).is_valid())
        self.assertTrue(self.request_form(self.any_season, self.soccer).is_valid())

    def test_pool_view_saves_the_season_sport(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("teams:free_agent_pool"),
            {"season": self.season.pk, "sport": self.soccer.pk},
        )
        self.assertRedirects(response, reverse("teams:free_agent_pool"))
        self.assertEqual(FreeAgentRequest.objects.get().sport, self.basketball)


class SeasonFormSportTests(SportRuleBase):
    def season_data(self, sport):
        return {
            "name": "Fall 2026",
            "sport": sport.pk if sport else "",
            "start_date": "2026-09-01",
            "end_date": "",
            "max_roster_size": 12,
        }

    def test_create_with_and_without_sport(self):
        form = SeasonForm(self.season_data(self.soccer))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().sport, self.soccer)
        form = SeasonForm(self.season_data(None))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().sport)

    def test_sport_field_is_optional_with_any_sport_label(self):
        field = SeasonForm().fields["sport"]
        self.assertFalse(field.required)
        self.assertEqual(field.empty_label, "Any sport")

    def test_sport_change_refused_when_team_of_another_sport_exists(self):
        Team.objects.create(
            name="Kickers", sport=self.soccer, season=self.any_season, captain=self.user
        )
        form = SeasonForm(self.season_data(self.basketball), instance=self.any_season)
        self.assertFalse(form.is_valid())
        self.assertIn("sport", form.errors)
        self.any_season.refresh_from_db()
        self.assertIsNone(self.any_season.sport)

    def test_sport_change_allowed_when_teams_match(self):
        Team.objects.create(
            name="Kickers", sport=self.soccer, season=self.any_season, captain=self.user
        )
        form = SeasonForm(self.season_data(self.soccer), instance=self.any_season)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().sport, self.soccer)

    def test_sport_change_allowed_in_empty_season(self):
        form = SeasonForm(self.season_data(self.soccer), instance=self.season)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().sport, self.soccer)

    def test_clearing_sport_is_always_allowed(self):
        Team.objects.create(
            name="Hoopers", sport=self.basketball, season=self.season, captain=self.user
        )
        form = SeasonForm(self.season_data(None), instance=self.season)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().sport)

    def test_admin_pages_show_the_sport(self):
        admin = make_user("admin1")
        assign_role(admin, LEAGUE_ADMIN_ROLE)
        self.client.force_login(admin)
        response = self.client.get(reverse("teams:manage_seasons"))
        self.assertContains(response, "Basketball ·")
        self.assertContains(response, "Any sport ·")
        response = self.client.get(reverse("teams:edit_season", args=[self.season.pk]))
        self.assertContains(response, 'name="sport"')
        self.assertContains(response, "Any sport")
