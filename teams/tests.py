import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import FreeAgentRequest, Roster, Season, Team


# TODO(T10): switch to the shared fixtures once they land.
def make_user(username, email=None):
    return get_user_model().objects.create_user(
        username=username, email=email or f"{username}@nyu.edu", password="pass12345!"
    )


def make_team(captain, name="Violets", season=None):
    team = Team.objects.create(
        name=name, sport="Soccer", captain=captain, season=season
    )
    Roster.objects.create(team=team, player=captain, role=Roster.Role.CAPTAIN)
    return team


class CreateTeamTests(TestCase):
    def setUp(self):
        self.user = make_user("cap")
        self.client.force_login(self.user)

    def test_creator_becomes_captain(self):
        response = self.client.post(
            reverse("teams:create"), {"name": "Violets", "sport": "Soccer"}
        )
        team = Team.objects.get(name="Violets")
        self.assertRedirects(response, reverse("teams:detail", args=[team.pk]))
        self.assertEqual(team.captain, self.user)
        self.assertTrue(
            Roster.objects.filter(
                team=team, player=self.user, role=Roster.Role.CAPTAIN
            ).exists()
        )

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("teams:create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class AddPlayerTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap")
        self.player = make_user("player")
        self.team = make_team(self.captain)
        self.url = reverse("teams:add_player", args=[self.team.pk])
        self.client.force_login(self.captain)

    def test_captain_adds_player_by_nyu_email(self):
        response = self.client.post(self.url, {"email": "PLAYER@nyu.edu"})
        self.assertRedirects(response, reverse("teams:detail", args=[self.team.pk]))
        self.assertTrue(
            Roster.objects.filter(
                team=self.team, player=self.player, role=Roster.Role.PLAYER
            ).exists()
        )

    def test_non_nyu_email_rejected(self):
        make_user("outsider", email="outsider@gmail.com")
        response = self.client.post(self.url, {"email": "outsider@gmail.com"})
        self.assertContains(response, "Only @nyu.edu emails can be added.")
        self.assertEqual(self.team.roster.count(), 1)

    def test_unknown_email_rejected(self):
        response = self.client.post(self.url, {"email": "nobody@nyu.edu"})
        self.assertContains(response, "No PlayNYU account with that email.")

    def test_duplicate_rejected(self):
        Roster.objects.create(team=self.team, player=self.player)
        response = self.client.post(self.url, {"email": "player@nyu.edu"})
        self.assertContains(response, "already on this team")
        self.assertEqual(self.team.roster.count(), 2)

    def test_non_captain_forbidden(self):
        self.client.force_login(self.player)
        response = self.client.post(self.url, {"email": "player@nyu.edu"})
        self.assertEqual(response.status_code, 403)


class RosterPageTests(TestCase):
    def test_roster_lists_members(self):
        captain = make_user("cap")
        team = make_team(captain)
        Roster.objects.create(team=team, player=make_user("player"))
        self.client.force_login(captain)
        response = self.client.get(reverse("teams:detail", args=[team.pk]))
        self.assertContains(response, "cap@nyu.edu")
        self.assertContains(response, "player@nyu.edu")
        self.assertContains(response, "Add a player")

    def test_non_member_gets_404(self):
        team = make_team(make_user("cap"))
        self.client.force_login(make_user("stranger"))
        response = self.client.get(reverse("teams:detail", args=[team.pk]))
        self.assertEqual(response.status_code, 404)

    def test_my_teams_lists_only_my_teams(self):
        me = make_user("me")
        make_team(me, name="Mine")
        make_team(make_user("other"), name="Theirs")
        self.client.force_login(me)
        response = self.client.get(reverse("teams:list"))
        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")


def make_season(name="Fall 2026", max_roster_size=12):
    return Season.objects.create(
        name=name, start_date=datetime.date(2026, 9, 1), max_roster_size=max_roster_size
    )


class RosterRuleTests(TestCase):
    def setUp(self):
        self.season = make_season(max_roster_size=2)
        self.captain = make_user("cap")
        self.team = make_team(self.captain, season=self.season)
        self.url = reverse("teams:add_player", args=[self.team.pk])
        self.client.force_login(self.captain)

    def test_full_roster_rejects_new_player(self):
        Roster.objects.create(team=self.team, player=make_user("p1"))
        make_user("p2")
        response = self.client.post(self.url, {"email": "p2@nyu.edu"})
        self.assertContains(response, "The roster is full (2 players).")
        self.assertEqual(self.team.roster.count(), 2)

    def test_full_roster_add_page_redirects_to_team(self):
        Roster.objects.create(team=self.team, player=make_user("p1"))
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("teams:detail", args=[self.team.pk]))

    def test_full_roster_hides_add_player(self):
        Roster.objects.create(team=self.team, player=make_user("p1"))
        response = self.client.get(reverse("teams:detail", args=[self.team.pk]))
        self.assertContains(response, "Roster full")
        self.assertNotContains(response, self.url)

    def test_team_without_season_uses_default_cap(self):
        team = make_team(make_user("cap2"), name="No season")
        self.assertEqual(team.max_roster_size, Team.DEFAULT_MAX_ROSTER_SIZE)

    def test_player_on_another_team_this_season_rejected(self):
        player = make_user("player")
        other = make_team(make_user("cap2"), name="Others", season=self.season)
        Roster.objects.create(team=other, player=player)
        response = self.client.post(self.url, {"email": "player@nyu.edu"})
        self.assertContains(response, "already on another team this season")
        self.assertFalse(self.team.roster.filter(player=player).exists())

    def test_player_on_team_in_other_season_allowed(self):
        player = make_user("player")
        other = make_team(
            make_user("cap2"), name="Others", season=make_season("Spring")
        )
        Roster.objects.create(team=other, player=player)
        self.client.post(self.url, {"email": "player@nyu.edu"})
        self.assertTrue(self.team.roster.filter(player=player).exists())

    def test_cannot_create_second_team_in_same_season(self):
        response = self.client.post(
            reverse("teams:create"),
            {"name": "Second", "sport": "Soccer", "season": self.season.pk},
        )
        self.assertContains(response, "Players can be on one team per season.")
        self.assertFalse(Team.objects.filter(name="Second").exists())

    def test_can_create_team_without_season(self):
        self.client.post(reverse("teams:create"), {"name": "Pickup", "sport": "Soccer"})
        self.assertTrue(Team.objects.filter(name="Pickup").exists())


class RemovePlayerTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap")
        self.player = make_user("player")
        self.team = make_team(self.captain)
        self.entry = Roster.objects.create(team=self.team, player=self.player)
        self.url = reverse("teams:remove_player", args=[self.team.pk, self.entry.pk])

    def test_captain_removes_player(self):
        self.client.force_login(self.captain)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("teams:detail", args=[self.team.pk]))
        self.assertFalse(self.team.roster.filter(player=self.player).exists())

    def test_non_captain_forbidden(self):
        self.client.force_login(self.player)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.team.roster.filter(player=self.player).exists())

    def test_captain_cannot_remove_self(self):
        self.client.force_login(self.captain)
        captain_entry = self.team.roster.get(player=self.captain)
        url = reverse("teams:remove_player", args=[self.team.pk, captain_entry.pk])
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(self.team.roster.filter(player=self.captain).exists())

    def test_entry_from_another_team_404(self):
        other = make_team(make_user("cap2"), name="Others")
        entry = Roster.objects.create(team=other, player=make_user("p2"))
        self.client.force_login(self.captain)
        url = reverse("teams:remove_player", args=[self.team.pk, entry.pk])
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_get_not_allowed(self):
        self.client.force_login(self.captain)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_remove_button_shown_to_captain_only(self):
        detail = reverse("teams:detail", args=[self.team.pk])
        self.client.force_login(self.captain)
        self.assertContains(self.client.get(detail), self.url)
        self.client.force_login(self.player)
        self.assertNotContains(self.client.get(detail), self.url)


class LeaveTeamTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap")
        self.player = make_user("player")
        self.team = make_team(self.captain)
        Roster.objects.create(team=self.team, player=self.player)
        self.url = reverse("teams:leave", args=[self.team.pk])

    def test_player_leaves(self):
        self.client.force_login(self.player)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("teams:list"))
        self.assertFalse(self.team.roster.filter(player=self.player).exists())

    def test_captain_cannot_leave(self):
        self.client.force_login(self.captain)
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, "Captains can&#x27;t leave their own team.")
        self.assertTrue(self.team.roster.filter(player=self.captain).exists())

    def test_non_member_404(self):
        self.client.force_login(make_user("stranger"))
        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_leaving_frees_season_slot(self):
        season = make_season()
        self.team.season = season
        self.team.save()
        self.client.force_login(self.player)
        self.client.post(self.url)
        self.client.post(
            reverse("teams:create"),
            {"name": "New", "sport": "Soccer", "season": season.pk},
        )
        self.assertTrue(Team.objects.filter(name="New").exists())


class FreeAgentRequestTests(TestCase):
    def setUp(self):
        self.season = make_season()
        self.player = make_user("freeagent")
        self.url = reverse("teams:free_agent_pool")
        self.client.force_login(self.player)

    def test_player_can_join_the_free_agent_pool(self):
        response = self.client.post(
            self.url, {"season": self.season.pk, "sport": "Soccer"}
        )
        self.assertRedirects(response, self.url)
        self.assertTrue(
            FreeAgentRequest.objects.filter(
                player=self.player, season=self.season, sport="Soccer"
            ).exists()
        )

    def test_player_can_cancel_their_request(self):
        request = FreeAgentRequest.objects.create(
            player=self.player, season=self.season, sport="Soccer"
        )
        response = self.client.post(
            reverse("teams:cancel_free_agent_request", args=[request.pk])
        )
        self.assertRedirects(response, self.url)
        self.assertFalse(FreeAgentRequest.objects.filter(pk=request.pk).exists())

    def test_player_cannot_cancel_another_players_request(self):
        request = FreeAgentRequest.objects.create(
            player=self.player, season=self.season, sport="Soccer"
        )
        other_player = make_user("other")
        self.client.force_login(other_player)
        response = self.client.post(
            reverse("teams:cancel_free_agent_request", args=[request.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(FreeAgentRequest.objects.filter(pk=request.pk).exists())

    def test_player_already_on_a_team_cannot_request_placement(self):
        team = make_team(make_user("captain"), season=self.season)
        Roster.objects.create(team=team, player=self.player)
        response = self.client.post(
            self.url, {"season": self.season.pk, "sport": "Soccer"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            FreeAgentRequest.objects.filter(
                player=self.player, season=self.season
            ).exists()
        )

    def test_inactive_season_rejects_a_request(self):
        self.season.is_active = False
        self.season.save(update_fields=["is_active"])
        response = self.client.post(
            self.url, {"season": self.season.pk, "sport": "Soccer"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FreeAgentRequest.objects.exists())


class FreeAgentMatchingTests(TestCase):
    def setUp(self):
        self.season = make_season(max_roster_size=2)
        self.captain = make_user("captain")
        self.team = make_team(self.captain, season=self.season)
        self.admin = make_user("leagueadmin")
        admin_group, _ = Group.objects.get_or_create(name="League Admin")
        self.admin.groups.add(admin_group)
        self.url = reverse("teams:manage_season_free_agents", args=[self.season.pk])

    def test_only_league_admin_can_manage_free_agents(self):
        self.client.force_login(make_user("player"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_admin_matches_requests_to_a_sport_team_with_space(self):
        player = make_user("poolplayer")
        request = FreeAgentRequest.objects.create(
            player=player, season=self.season, sport="soccer"
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("teams:match_free_agents", args=[self.season.pk])
        )
        self.assertRedirects(response, self.url)
        self.assertTrue(self.team.roster.filter(player=player).exists())
        self.assertFalse(FreeAgentRequest.objects.filter(pk=request.pk).exists())

    def test_requests_stay_pending_when_no_matching_team_has_space(self):
        player = make_user("poolplayer")
        request = FreeAgentRequest.objects.create(
            player=player, season=self.season, sport="Basketball"
        )
        self.client.force_login(self.admin)
        self.client.post(reverse("teams:match_free_agents", args=[self.season.pk]))
        self.assertFalse(self.team.roster.filter(player=player).exists())
        self.assertTrue(FreeAgentRequest.objects.filter(pk=request.pk).exists())
