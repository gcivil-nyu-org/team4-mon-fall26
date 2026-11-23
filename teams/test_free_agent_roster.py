"""A player on a team that season isn't a free agent (#296)."""

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE

from .models import FreeAgentRequest, Roster, Sport
from .tests import make_season, make_team, make_user


class CreateTeamLeavesFreeAgentPoolTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.get_or_create(name="Soccer")[0]
        self.season = make_season()
        self.other_season = make_season(name="Spring 2027")
        self.user = make_user("fa")
        self.client.force_login(self.user)

    def request_placement(self, season):
        return FreeAgentRequest.objects.create(
            player=self.user, season=season, sport=self.sport
        )

    def test_creating_a_team_removes_that_seasons_request(self):
        self.request_placement(self.season)
        kept = self.request_placement(self.other_season)
        self.client.post(
            reverse("teams:create"),
            {"name": "XI", "sport": self.sport.pk, "season": self.season.pk},
        )
        self.assertEqual(
            list(FreeAgentRequest.objects.filter(player=self.user)), [kept]
        )

    def test_pool_hides_a_stale_request_from_a_rostered_player(self):
        stale = self.request_placement(self.season)
        waiting = FreeAgentRequest.objects.create(
            player=make_user("waiting"), season=self.season, sport=self.sport
        )
        team = make_team(make_user("cap"), season=self.season)
        Roster.objects.create(team=team, player=self.user)
        response = self.client.get(
            reverse("teams:free_agent_pool"), {"season": self.season.pk}
        )
        shown = list(response.context["free_agents"])
        self.assertIn(waiting, shown)
        self.assertNotIn(stale, shown)

        admin = make_user("admin")
        admin.groups.add(Group.objects.get_or_create(name=LEAGUE_ADMIN_ROLE)[0])
        self.client.force_login(admin)
        response = self.client.get(
            reverse("teams:manage_season_free_agents", args=[self.season.pk])
        )
        self.assertEqual(list(response.context["free_agents"]), [waiting])
