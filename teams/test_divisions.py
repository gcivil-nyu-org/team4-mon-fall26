import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role

from .forms import FreeAgentRequestForm, TeamCreateForm
from .models import Division, FreeAgentRequest, Roster, Season, Team


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


def make_season(name):
    return Season.objects.create(name=name, start_date=datetime.date(2026, 9, 1))


def make_team(captain, season, division=None, name="Violets"):
    team = Team.objects.create(
        name=name,
        sport="Soccer",
        season=season,
        division=division,
        captain=captain,
    )
    Roster.objects.create(team=team, player=captain, role=Roster.Role.CAPTAIN)
    return team


class DivisionModelTests(TestCase):
    def setUp(self):
        self.season = make_season("Fall")
        self.other_season = make_season("Spring")
        self.division = Division.objects.create(
            season=self.season, name="  west\tdivision  "
        )

    def test_division_name_is_normalized_and_unique_within_season(self):
        self.assertEqual(self.division.name, "west division")
        self.assertEqual(self.division.name_key, "west division")
        with self.assertRaises(ValidationError):
            Division.objects.create(season=self.season, name=" WEST   DIVISION ")

    def test_same_division_name_is_allowed_in_another_season(self):
        other = Division.objects.create(season=self.other_season, name="WEST DIVISION")
        self.assertEqual(other.name, "WEST DIVISION")

    def test_team_model_rejects_a_division_from_another_season(self):
        team = Team(
            name="Cross season",
            sport="Soccer",
            season=self.other_season,
            division=self.division,
            captain=make_user("captain"),
        )
        with self.assertRaisesMessage(
            ValidationError, "Choose a division from this team's season."
        ):
            team.save()

    def test_free_agent_request_model_rejects_a_division_from_another_season(self):
        request = FreeAgentRequest(
            player=make_user("freeagent"),
            season=self.other_season,
            division=self.division,
            sport="Soccer",
        )
        with self.assertRaisesMessage(
            ValidationError, "Choose a division from the requested season."
        ):
            request.save()


class DivisionSelectionFormTests(TestCase):
    def setUp(self):
        self.season = make_season("Fall")
        self.other_season = make_season("Spring")
        self.division = Division.objects.create(season=self.season, name="West")
        self.other_division = Division.objects.create(
            season=self.other_season, name="West"
        )
        self.player = make_user("player")

    def test_team_can_choose_a_division_in_its_season(self):
        form = TeamCreateForm(
            {
                "name": "Violets",
                "sport": "Soccer",
                "season": self.season.pk,
                "division": self.division.pk,
            },
            user=self.player,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_team_creation_saves_the_chosen_division(self):
        self.client.force_login(self.player)
        response = self.client.post(
            reverse("teams:create"),
            {
                "name": "Violets",
                "sport": "Soccer",
                "season": self.season.pk,
                "division": self.division.pk,
            },
        )
        team = Team.objects.get(name="Violets")
        self.assertEqual(team.division, self.division)
        self.assertRedirects(response, reverse("teams:detail", args=[team.pk]))

    def test_team_cannot_choose_a_division_from_another_season(self):
        form = TeamCreateForm(
            {
                "name": "Violets",
                "sport": "Soccer",
                "season": self.season.pk,
                "division": self.other_division.pk,
            },
            user=self.player,
        )
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Choose a division from the selected season.", form.errors["division"]
        )

    def test_free_agent_request_can_choose_a_division_in_its_season(self):
        form = FreeAgentRequestForm(
            {
                "season": self.season.pk,
                "sport": "Soccer",
                "division": self.division.pk,
            },
            user=self.player,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_free_agent_request_saves_the_chosen_division(self):
        self.client.force_login(self.player)
        response = self.client.post(
            reverse("teams:free_agent_pool"),
            {
                "season": self.season.pk,
                "sport": "Soccer",
                "division": self.division.pk,
            },
        )
        request = FreeAgentRequest.objects.get(player=self.player, season=self.season)
        self.assertEqual(request.division, self.division)
        self.assertRedirects(response, reverse("teams:free_agent_pool"))

    def test_free_agent_request_cannot_choose_a_division_from_another_season(self):
        form = FreeAgentRequestForm(
            {
                "season": self.season.pk,
                "sport": "Soccer",
                "division": self.other_division.pk,
            },
            user=self.player,
        )
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Choose a division from the selected season.", form.errors["division"]
        )

    def test_team_without_division_remains_valid(self):
        form = TeamCreateForm(
            {"name": "Unassigned", "sport": "Soccer", "season": self.season.pk},
            user=self.player,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["division"])


class DivisionManagementTests(TestCase):
    def setUp(self):
        self.season = make_season("Fall")
        self.url = reverse("teams:manage_season_divisions", args=[self.season.pk])

    def test_only_league_admin_can_manage_divisions(self):
        self.client.force_login(make_user("player"))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("teams:manage_divisions")).status_code, 403
        )

        admin = make_user("leagueadmin")
        assign_role(admin, LEAGUE_ADMIN_ROLE)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_league_admin_can_choose_any_season_for_division_setup(self):
        admin = make_user("leagueadmin")
        assign_role(admin, LEAGUE_ADMIN_ROLE)
        self.client.force_login(admin)
        response = self.client.get(reverse("teams:manage_divisions"))
        self.assertContains(response, self.season.name)
        self.assertContains(
            response, reverse("teams:manage_season_divisions", args=[self.season.pk])
        )

    def test_league_admin_can_add_a_division(self):
        admin = make_user("leagueadmin")
        assign_role(admin, LEAGUE_ADMIN_ROLE)
        self.client.force_login(admin)
        response = self.client.post(self.url, {"name": "North"})
        self.assertRedirects(response, self.url)
        self.assertTrue(
            Division.objects.filter(season=self.season, name="North").exists()
        )

    def test_division_names_are_unique_ignoring_case_and_whitespace(self):
        Division.objects.create(season=self.season, name="West Division")
        admin = make_user("leagueadmin")
        assign_role(admin, LEAGUE_ADMIN_ROLE)
        self.client.force_login(admin)
        response = self.client.post(self.url, {"name": " west   division "})
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "A division with this name already exists in this season."
        )
        self.assertEqual(Division.objects.filter(season=self.season).count(), 1)


class DivisionAwareMatchingTests(TestCase):
    def setUp(self):
        self.season = make_season("Fall")
        self.west = Division.objects.create(season=self.season, name="West")
        self.east = Division.objects.create(season=self.season, name="East")
        self.unmatched = Division.objects.create(season=self.season, name="North")
        self.west_team = make_team(
            make_user("westcaptain"), self.season, self.west, "West Violets"
        )
        self.east_team = make_team(
            make_user("eastcaptain"), self.season, self.east, "East Violets"
        )
        self.west_player = make_user("westplayer")
        self.east_player = make_user("eastplayer")
        self.any_player = make_user("anyplayer")
        self.north_player = make_user("northplayer")
        FreeAgentRequest.objects.create(
            player=self.west_player,
            season=self.season,
            sport="Soccer",
            division=self.west,
        )
        FreeAgentRequest.objects.create(
            player=self.east_player,
            season=self.season,
            sport="Soccer",
            division=self.east,
        )
        FreeAgentRequest.objects.create(
            player=self.any_player, season=self.season, sport="Soccer"
        )
        self.north_request = FreeAgentRequest.objects.create(
            player=self.north_player,
            season=self.season,
            sport="Soccer",
            division=self.unmatched,
        )
        admin = make_user("leagueadmin")
        assign_role(admin, LEAGUE_ADMIN_ROLE)
        self.client.force_login(admin)

    def test_matching_respects_divisions_but_unassigned_requests_can_join_any_team(
        self,
    ):
        response = self.client.post(
            reverse("teams:match_free_agents", args=[self.season.pk])
        )
        self.assertRedirects(
            response,
            reverse("teams:manage_season_free_agents", args=[self.season.pk]),
        )
        self.assertTrue(
            Roster.objects.filter(team=self.west_team, player=self.west_player).exists()
        )
        self.assertTrue(
            Roster.objects.filter(team=self.east_team, player=self.east_player).exists()
        )
        self.assertTrue(
            Roster.objects.filter(
                player=self.any_player, team__in=[self.west_team, self.east_team]
            ).exists()
        )
        self.assertTrue(
            FreeAgentRequest.objects.filter(pk=self.north_request.pk).exists()
        )
