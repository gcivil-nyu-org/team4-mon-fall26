"""Captains can delete an empty team (#272)."""

import datetime

from django.test import TestCase
from django.urls import reverse

from chat.models import Conversation
from facilities.models import Facility
from matches.models import Match

from .models import Roster, Sport, Team
from .season_rules import SeasonState
from .tests import make_season, make_team, make_user, message_texts


class DisbandTeamTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.get_or_create(name="Soccer")[0]
        self.season = make_season()
        self.captain = make_user("cap")
        self.team = make_team(self.captain, season=self.season)
        self.url = reverse("teams:disband", args=[self.team.pk])
        self.detail = reverse("teams:detail", args=[self.team.pk])
        self.client.force_login(self.captain)

    def test_captain_deletes_empty_team(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("teams:list"))
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())
        self.assertFalse(Roster.objects.filter(player=self.captain).exists())
        self.assertFalse(Conversation.objects.filter(team_id=self.team.pk).exists())
        self.assertIn("You deleted Violets.", message_texts(response))

    def test_captain_can_create_another_team_in_the_season_after(self):
        self.client.post(self.url)
        self.client.post(
            reverse("teams:create"),
            {"name": "Second", "sport": self.sport.pk, "season": self.season.pk},
        )
        self.assertTrue(Team.objects.filter(name="Second").exists())

    def test_detail_shows_delete_button_for_empty_team(self):
        response = self.client.get(self.detail)
        self.assertContains(response, f'action="{self.url}"')

    def assert_blocked(self, reason):
        response = self.client.post(self.url)
        self.assertRedirects(response, self.detail)
        self.assertTrue(Team.objects.filter(pk=self.team.pk).exists())
        self.assertIn(reason, message_texts(response))
        page = self.client.get(self.detail)
        self.assertNotContains(page, f'action="{self.url}"')
        self.assertContains(page, "Delete team")
        self.assertContains(page, reason.replace("'", "&#x27;"))

    def test_blocked_with_other_players(self):
        Roster.objects.create(team=self.team, player=make_user("player"))
        self.assert_blocked("Remove the other players before you delete the team.")

    def test_blocked_with_matches(self):
        other = make_team(make_user("cap2"), name="Bobcats", season=self.season)
        Match.objects.create(
            season=self.season,
            home_team=self.team,
            away_team=other,
            facility=Facility.objects.create(
                name="Pier 40", source=Facility.Source.NYU
            ),
            starts_at=datetime.datetime(2026, 11, 10, 18, 0, tzinfo=datetime.UTC),
            ends_at=datetime.datetime(2026, 11, 10, 20, 0, tzinfo=datetime.UTC),
        )
        self.assert_blocked("This team has matches. Ask a League Admin to delete it.")

    def test_blocked_once_season_starts(self):
        self.season.state = SeasonState.ACTIVE
        self.season.save()
        self.assert_blocked("Teams can't be deleted once the season starts.")

    def test_non_captain_forbidden(self):
        player = make_user("player")
        Roster.objects.create(team=self.team, player=player)
        self.client.force_login(player)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(Team.objects.filter(pk=self.team.pk).exists())

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_leave_message_points_captain_to_delete(self):
        response = self.client.post(reverse("teams:leave", args=[self.team.pk]))
        self.assertIn(
            "Captains can't leave their own team. To remove an empty team, "
            "use Delete team.",
            message_texts(response),
        )
