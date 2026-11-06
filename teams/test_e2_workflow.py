"""#109: one season end to end, through the pages, as docs/E2_CONTRACT.md describes.

create sport -> create season (draft) -> open -> divisions -> teams -> free-agent
requests -> match (divisions respected) -> active (rosters locked) -> closed.
"""

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role

from .models import Division, FreeAgentRequest, Roster, Season, Sport, Team
from .season_rules import SeasonState


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


def message_texts(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


class SeasonEndToEndTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin")
        assign_role(self.admin, LEAGUE_ADMIN_ROLE)
        self.west_captain = make_user("westcap")
        self.east_captain = make_user("eastcap")
        self.east_agent = make_user("eastagent")
        self.any_agent = make_user("anyagent")
        self.late_player = make_user("late")

    def as_user(self, user):
        self.client.force_login(user)
        return self.client

    def set_state(self, season, state):
        return self.as_user(self.admin).post(
            reverse("teams:change_season_state", args=[season.pk]), {"state": state}
        )

    def create_team(self, captain, name, division):
        return self.as_user(captain).post(
            reverse("teams:create"),
            {
                "name": name,
                "sport": self.sport.pk,
                "season": self.season.pk,
                "division": division.pk if division else "",
            },
        )

    def request_placement(self, player, division):
        return self.as_user(player).post(
            reverse("teams:free_agent_pool"),
            {
                "season": self.season.pk,
                "sport": self.sport.pk,
                "division": division.pk if division else "",
            },
        )

    def team_of(self, player):
        entry = Roster.objects.filter(player=player, team__season=self.season).first()
        return entry.team if entry else None

    def test_full_season_lifecycle(self):
        admin = self.as_user(self.admin)

        # 1. Sport.
        response = admin.post(reverse("teams:manage_sports"), {"name": "Soccer"})
        self.assertIn("Sport added successfully.", message_texts(response))
        self.sport = Sport.objects.get(name="Soccer")

        # 2. Season starts as a draft that players can't use.
        response = admin.post(
            reverse("teams:create_season"),
            {"name": "Fall 2026", "start_date": "2026-09-01", "max_roster_size": 12},
        )
        self.season = Season.objects.get(name="Fall 2026")
        self.assertEqual(self.season.state, SeasonState.DRAFT)
        self.assertIn(
            "Created Fall 2026 as a draft. Players see it once you open registration.",
            message_texts(response),
        )
        response = self.as_user(self.west_captain).get(reverse("teams:create"))
        self.assertNotIn(
            self.season, response.context["form"].fields["season"].queryset
        )
        response = self.as_user(self.east_agent).get(reverse("teams:free_agent_pool"))
        self.assertNotIn(
            self.season, response.context["form"].fields["season"].queryset
        )

        # 3. Open registration and add divisions.
        response = self.set_state(self.season, SeasonState.OPEN)
        self.assertIn("Fall 2026 is now open.", message_texts(response))
        for name in ("West", "East"):
            self.as_user(self.admin).post(
                reverse("teams:manage_season_divisions", args=[self.season.pk]),
                {"name": name},
            )
        west = Division.objects.get(season=self.season, name="West")
        east = Division.objects.get(season=self.season, name="East")

        # 4. Captains register teams. West is created first, so it has the lower pk
        #    and would win a tie if divisions were ignored.
        self.create_team(self.west_captain, "West FC", west)
        self.create_team(self.east_captain, "East FC", east)
        west_fc = Team.objects.get(name="West FC")
        east_fc = Team.objects.get(name="East FC")
        self.assertEqual((west_fc.division, east_fc.division), (west, east))

        # 5. Free agents: one for East only, one for any division (requested later).
        self.request_placement(self.east_agent, east)
        self.request_placement(self.any_agent, None)
        self.assertEqual(FreeAgentRequest.objects.filter(season=self.season).count(), 2)

        # 6. Matching respects the division, then fills the smaller team.
        response = self.as_user(self.admin).post(
            reverse("teams:match_free_agents", args=[self.season.pk])
        )
        self.assertIn("Placed 2 player(s) in Fall 2026.", message_texts(response))
        self.assertEqual(self.team_of(self.east_agent), east_fc)
        self.assertEqual(self.team_of(self.any_agent), west_fc)
        self.assertFalse(FreeAgentRequest.objects.filter(season=self.season).exists())

        # 7. Active: no new teams, rosters locked, adding players still allowed.
        response = self.set_state(self.season, SeasonState.ACTIVE)
        self.assertIn("Fall 2026 is now active.", message_texts(response))

        response = self.create_team(self.late_player, "Late FC", None)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Team.objects.filter(name="Late FC").exists())

        entry = Roster.objects.get(team=east_fc, player=self.east_agent)
        response = self.as_user(self.east_captain).post(
            reverse("teams:remove_player", args=[east_fc.pk, entry.pk])
        )
        self.assertIn(
            "Rosters are locked once the season starts, so players can't be removed.",
            message_texts(response),
        )
        response = self.as_user(self.east_agent).post(
            reverse("teams:leave", args=[east_fc.pk])
        )
        self.assertIn(
            "Rosters are locked once the season starts, so you can't leave this team.",
            message_texts(response),
        )
        self.assertEqual(self.team_of(self.east_agent), east_fc)

        self.as_user(self.east_captain).post(
            reverse("teams:add_player", args=[east_fc.pk]),
            {"email": self.late_player.email},
        )
        self.assertEqual(self.team_of(self.late_player), east_fc)

        # 8. Closed: final and read-only.
        response = self.set_state(self.season, SeasonState.CLOSED)
        self.assertIn("Fall 2026 is now closed.", message_texts(response))

        response = self.set_state(self.season, SeasonState.OPEN)
        self.assertIn(
            "A season can't move from Closed to Open.", message_texts(response)
        )

        response = self.as_user(self.admin).get(
            reverse("teams:edit_season", args=[self.season.pk])
        )
        self.assertRedirects(response, reverse("teams:manage_seasons"))
        self.assertIn(
            "Fall 2026 is closed and can't be edited.", message_texts(response)
        )

        response = self.as_user(self.east_captain).post(
            reverse("teams:add_player", args=[east_fc.pk]),
            {"email": self.west_captain.email},
        )
        self.assertIn(
            "This season isn't accepting new players.", message_texts(response)
        )
        self.assertEqual(self.team_of(self.west_captain), west_fc)

        response = self.as_user(self.admin).post(
            reverse("teams:match_free_agents", args=[self.season.pk])
        )
        self.assertEqual(response.status_code, 404)

        self.season.refresh_from_db()
        self.assertEqual(self.season.state, SeasonState.CLOSED)
        self.assertEqual(
            sorted(
                Roster.objects.filter(team=east_fc).values_list(
                    "player__username", flat=True
                )
            ),
            ["eastagent", "eastcap", "late"],
        )
