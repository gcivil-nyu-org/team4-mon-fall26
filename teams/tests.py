from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Roster, Team


# TODO(T10): switch to the shared fixtures once they land.
def make_user(username, email=None):
    return get_user_model().objects.create_user(
        username=username, email=email or f"{username}@nyu.edu", password="pass12345!"
    )


def make_team(captain, name="Violets"):
    team = Team.objects.create(name=name, sport="Soccer", captain=captain)
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
