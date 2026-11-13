"""Roster capacity and one team per season, on every path onto a team (#135)."""

import datetime
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from .models import FreeAgentRequest, Roster, Season, Sport, Team
from .season_rules import SeasonState

FULL_MESSAGE = "The roster is full (2 players)."
OTHER_TEAM_MESSAGE = "That player is already on another team this season."


def make_user(username, **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@nyu.edu",
        password="pass12345!",
        **kwargs,
    )


def make_season(name="Fall 2026", max_roster_size=2, state=SeasonState.OPEN):
    return Season.objects.create(
        name=name,
        start_date=datetime.date(2026, 9, 1),
        state=state,
        max_roster_size=max_roster_size,
    )


def make_team(captain, name="Violets", season=None):
    sport, _ = Sport.objects.get_or_create(name="Soccer")
    team = Team.objects.create(name=name, sport=sport, captain=captain, season=season)
    Roster.objects.create(team=team, player=captain, role=Roster.Role.CAPTAIN)
    return team


class RosterModelTests(TestCase):
    """The model is the rule of last resort for anything that saves a Roster."""

    def setUp(self):
        self.season = make_season()
        self.team = make_team(make_user("cap"), season=self.season)
        self.other = make_team(make_user("cap2"), name="Others", season=self.season)
        self.player = make_user("player")

    def test_second_team_in_a_season_is_rejected(self):
        Roster.objects.create(team=self.other, player=self.player)
        with self.assertRaisesMessage(ValidationError, OTHER_TEAM_MESSAGE):
            Roster.objects.create(team=self.team, player=self.player)
        self.assertFalse(self.team.roster.filter(player=self.player).exists())

    def test_captain_role_does_not_get_round_the_season_rule(self):
        Roster.objects.create(team=self.other, player=self.player)
        with self.assertRaisesMessage(ValidationError, OTHER_TEAM_MESSAGE):
            Roster.objects.create(
                team=self.team, player=self.player, role=Roster.Role.CAPTAIN
            )

    def test_teams_in_different_seasons_are_allowed(self):
        later = make_team(
            make_user("cap3"), name="Later", season=make_season("Spring 2027")
        )
        Roster.objects.create(team=self.team, player=self.player)
        Roster.objects.create(team=later, player=self.player)
        self.assertEqual(self.player.roster_entries.count(), 2)

    def test_teams_with_no_season_do_not_count(self):
        first = make_team(make_user("cap3"), name="Pickup A")
        second = make_team(make_user("cap4"), name="Pickup B")
        Roster.objects.create(team=first, player=self.player)
        Roster.objects.create(team=second, player=self.player)
        Roster.objects.create(team=self.team, player=self.player)
        self.assertEqual(self.player.roster_entries.count(), 3)

    def test_full_roster_is_rejected(self):
        Roster.objects.create(team=self.team, player=self.player)
        with self.assertRaisesMessage(ValidationError, FULL_MESSAGE):
            Roster.objects.create(team=self.team, player=make_user("late"))
        self.assertEqual(self.team.roster.count(), 2)

    def test_team_with_no_season_has_the_default_cap(self):
        team = make_team(make_user("cap3"), name="Pickup")
        for number in range(Team.DEFAULT_MAX_ROSTER_SIZE - 1):
            Roster.objects.create(team=team, player=make_user(f"p{number}"))
        with self.assertRaisesMessage(ValidationError, "The roster is full (12 "):
            Roster.objects.create(team=team, player=make_user("late"))

    def test_same_player_twice_on_a_team_still_hits_the_unique_constraint(self):
        roomy = make_team(
            make_user("cap3"), name="Roomy", season=make_season("Roomy", 5)
        )
        Roster.objects.create(team=roomy, player=self.player)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Roster.objects.create(team=roomy, player=self.player)

    def test_moving_a_row_to_a_full_team_is_rejected(self):
        entry = Roster.objects.create(team=self.team, player=self.player)
        Roster.objects.create(team=self.other, player=make_user("p2"))
        entry.team = self.other
        with self.assertRaisesMessage(ValidationError, FULL_MESSAGE):
            entry.save()

    def test_swapping_a_row_to_a_player_on_another_team_is_rejected(self):
        entry = Roster.objects.create(team=self.team, player=make_user("p2"))
        Roster.objects.create(team=self.other, player=self.player)
        entry.player = self.player
        with self.assertRaisesMessage(ValidationError, OTHER_TEAM_MESSAGE):
            entry.save()

    def test_editing_a_row_on_a_roster_over_a_lowered_cap_still_works(self):
        entry = Roster.objects.create(team=self.team, player=self.player)
        Season.objects.filter(pk=self.season.pk).update(max_roster_size=1)
        entry = Roster.objects.get(pk=entry.pk)
        entry.role = Roster.Role.CAPTAIN
        entry.save()
        entry.refresh_from_db()
        self.assertEqual(entry.role, Roster.Role.CAPTAIN)


class TeamSeasonMoveTests(TestCase):
    """Changing Team.season puts its whole roster in the new season."""

    def setUp(self):
        self.season = make_season()
        self.target = make_season("Spring 2027")
        self.team = make_team(make_user("cap"), season=self.season)
        self.player = make_user("player")
        Roster.objects.create(team=self.team, player=self.player)

    def test_move_is_rejected_when_a_player_is_on_a_team_there(self):
        other = make_team(make_user("cap2"), name="Others", season=self.target)
        Roster.objects.create(team=other, player=self.player)
        self.team.season = self.target
        with self.assertRaisesMessage(ValidationError, "already on another team"):
            self.team.save()

    def test_move_is_rejected_when_the_roster_is_over_the_new_cap(self):
        small = make_season("Small", max_roster_size=1)
        self.team.season = small
        with self.assertRaisesMessage(ValidationError, "too many players"):
            self.team.save()

    def test_move_to_no_season_uses_the_default_cap(self):
        big = make_season("Big", max_roster_size=20)
        team = make_team(make_user("cap2"), name="Big team", season=big)
        for number in range(Team.DEFAULT_MAX_ROSTER_SIZE):
            Roster.objects.create(team=team, player=make_user(f"p{number}"))
        team.season = None
        with self.assertRaisesMessage(ValidationError, "too many players"):
            team.save()

    def test_move_without_a_clash_is_allowed(self):
        self.team.season = self.target
        self.team.save()
        self.team.refresh_from_db()
        self.assertEqual(self.team.season, self.target)

    def test_saving_without_moving_is_not_rechecked(self):
        Season.objects.filter(pk=self.season.pk).update(max_roster_size=1)
        team = Team.objects.get(pk=self.team.pk)
        team.name = "Renamed"
        team.save()
        self.assertEqual(Team.objects.get(pk=team.pk).name, "Renamed")


class CreateTeamPathTests(TestCase):
    def setUp(self):
        self.season = make_season()
        self.sport = Sport.objects.create(name="Soccer")
        self.player = make_user("player")
        self.client.force_login(self.player)
        self.url = reverse("teams:create")

    def post(self, name="Second"):
        return self.client.post(
            self.url,
            {"name": name, "sport": self.sport.pk, "season": self.season.pk},
        )

    def test_player_on_a_team_as_a_player_cannot_create_one_in_the_season(self):
        other = make_team(make_user("cap"), name="Others", season=self.season)
        Roster.objects.create(team=other, player=self.player)
        response = self.post()
        self.assertContains(response, "Players can be on one team per season.")
        self.assertFalse(Team.objects.filter(name="Second").exists())

    def test_captain_is_counted_on_the_new_roster(self):
        self.post("Mine")
        team = Team.objects.get(name="Mine")
        self.assertEqual(team.roster.count(), 1)
        self.assertEqual(team.roster.get().role, Roster.Role.CAPTAIN)

    def test_season_with_no_spots_rejects_the_team_with_a_message(self):
        Season.objects.filter(pk=self.season.pk).update(max_roster_size=0)
        response = self.post()
        self.assertContains(response, "can&#x27;t take a new team")
        self.assertFalse(Team.objects.filter(name="Second").exists())


class AddPlayerPathTests(TestCase):
    def setUp(self):
        self.season = make_season()
        self.captain = make_user("cap")
        self.team = make_team(self.captain, season=self.season)
        self.url = reverse("teams:add_player", args=[self.team.pk])
        self.client.force_login(self.captain)

    def test_full_roster_message_wins_over_season_clash_and_adds_nobody(self):
        Roster.objects.create(team=self.team, player=make_user("p1"))
        other = make_team(make_user("cap2"), name="Others", season=self.season)
        player = make_user("player")
        Roster.objects.create(team=other, player=player)
        response = self.client.post(self.url, {"email": player.email})
        self.assertContains(response, FULL_MESSAGE)
        self.assertEqual(player.roster_entries.count(), 1)

    def test_active_season_keeps_both_rules(self):
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.ACTIVE)
        other = make_team(make_user("cap2"), name="Others", season=self.season)
        player = make_user("player")
        Roster.objects.create(team=other, player=player)
        response = self.client.post(self.url, {"email": player.email})
        self.assertContains(response, OTHER_TEAM_MESSAGE)
        self.assertFalse(self.team.roster.filter(player=player).exists())

    def test_placed_player_leaves_the_free_agent_pool(self):
        player = make_user("player")
        FreeAgentRequest.objects.create(
            player=player, season=self.season, sport=self.team.sport
        )
        self.client.post(self.url, {"email": player.email})
        self.assertTrue(self.team.roster.filter(player=player).exists())
        self.assertFalse(FreeAgentRequest.objects.filter(player=player).exists())


class FreeAgentMatchingPathTests(TestCase):
    def setUp(self):
        self.season = make_season()
        self.team = make_team(make_user("cap"), season=self.season)
        self.sport = self.team.sport
        self.url = reverse("teams:match_free_agents", args=[self.season.pk])
        admin_user = make_user("leagueadmin")
        admin_user.groups.add(Group.objects.get_or_create(name="League Admin")[0])
        self.client.force_login(admin_user)

    def pool(self, *usernames):
        return [
            FreeAgentRequest.objects.create(
                player=make_user(name), season=self.season, sport=self.sport
            )
            for name in usernames
        ]

    def test_full_team_leaves_the_request_in_the_pool_with_a_message(self):
        Roster.objects.create(team=self.team, player=make_user("p1"))
        request = self.pool("late")[0]
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, "no eligible team with an open spot")
        self.assertEqual(self.team.roster.count(), 2)
        self.assertTrue(FreeAgentRequest.objects.filter(pk=request.pk).exists())

    def test_matching_stops_at_capacity_within_one_run(self):
        first, second, third = self.pool("a", "b", "c")
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, "Placed 1 player(s). 2 remain in the pool")
        self.assertEqual(self.team.roster.count(), 2)
        self.assertTrue(self.team.roster.filter(player=first.player).exists())
        self.assertEqual(FreeAgentRequest.objects.count(), 2)

    def test_player_who_joined_a_team_meanwhile_is_not_placed_twice(self):
        request = self.pool("joined")[0]
        other = make_team(make_user("cap2"), name="Others", season=self.season)
        Roster.objects.create(team=other, player=request.player)
        self.client.post(self.url)
        self.assertEqual(request.player.roster_entries.count(), 1)
        self.assertFalse(self.team.roster.filter(player=request.player).exists())
        self.assertFalse(FreeAgentRequest.objects.filter(pk=request.pk).exists())


class FreeAgentPoolPathTests(TestCase):
    def test_player_on_a_team_cannot_enter_the_pool_for_that_season(self):
        season = make_season()
        team = make_team(make_user("cap"), season=season)
        player = make_user("player")
        Roster.objects.create(team=team, player=player)
        self.client.force_login(player)
        self.client.post(
            reverse("teams:free_agent_pool"),
            {"season": season.pk, "sport": team.sport.pk},
        )
        self.assertFalse(FreeAgentRequest.objects.filter(player=player).exists())


class AdminPathTests(TestCase):
    def setUp(self):
        self.season = make_season()
        self.captain = make_user("cap")
        self.team = make_team(self.captain, season=self.season)
        self.sport = self.team.sport
        self.other_captain = make_user("cap2")
        self.other = make_team(self.other_captain, name="Others", season=self.season)
        self.player = make_user("player")
        self.client.force_login(
            get_user_model().objects.create_superuser(
                username="root", email="root@nyu.edu", password="pass12345!"
            )
        )

    def team_data(self, team=None, rows=(), **fields):
        """A TeamAdmin POST. rows are (player, role, entry) with entry None for new."""
        data = {
            "name": team.name if team else "New team",
            "sport": self.sport.pk,
            "season": self.season.pk,
            "division": "",
            "captain": self.captain.pk,
            "roster-TOTAL_FORMS": len(rows),
            "roster-INITIAL_FORMS": sum(1 for row in rows if row[2]),
            "roster-MIN_NUM_FORMS": 0,
            "roster-MAX_NUM_FORMS": 1000,
            "_save": "Save",
            **fields,
        }
        for index, (player, role, entry) in enumerate(rows):
            data[f"roster-{index}-player"] = player.pk
            data[f"roster-{index}-role"] = role
            data[f"roster-{index}-id"] = entry.pk if entry else ""
            data[f"roster-{index}-team"] = team.pk if team else ""
        return data

    def existing_rows(self, team):
        return [(e.player, e.role, e) for e in team.roster.order_by("pk")]

    def change_url(self, team):
        return reverse("admin:teams_team_change", args=[team.pk])

    def test_roster_admin_add_rejects_a_second_team_in_the_season(self):
        Roster.objects.create(team=self.other, player=self.player)
        response = self.client.post(
            reverse("admin:teams_roster_add"),
            {"team": self.team.pk, "player": self.player.pk, "role": "player"},
        )
        self.assertContains(response, OTHER_TEAM_MESSAGE)
        self.assertFalse(self.team.roster.filter(player=self.player).exists())

    def test_roster_admin_add_rejects_a_full_roster(self):
        Roster.objects.create(team=self.team, player=make_user("p1"))
        response = self.client.post(
            reverse("admin:teams_roster_add"),
            {"team": self.team.pk, "player": self.player.pk, "role": "player"},
        )
        self.assertContains(response, FULL_MESSAGE)
        self.assertEqual(self.team.roster.count(), 2)

    def test_roster_admin_change_rejects_a_move_to_a_full_team(self):
        entry = Roster.objects.create(team=self.team, player=self.player)
        Roster.objects.create(team=self.other, player=make_user("p1"))
        response = self.client.post(
            reverse("admin:teams_roster_change", args=[entry.pk]),
            {"team": self.other.pk, "player": self.player.pk, "role": "player"},
        )
        self.assertContains(response, FULL_MESSAGE)
        entry.refresh_from_db()
        self.assertEqual(entry.team, self.team)

    def test_team_inline_rejects_a_second_team_in_the_season(self):
        Roster.objects.create(team=self.other, player=self.player)
        rows = self.existing_rows(self.team) + [(self.player, "player", None)]
        response = self.client.post(
            self.change_url(self.team), self.team_data(self.team, rows)
        )
        self.assertContains(response, OTHER_TEAM_MESSAGE)
        self.assertFalse(self.team.roster.filter(player=self.player).exists())

    def test_team_inline_rejects_several_new_rows_over_the_cap(self):
        rows = self.existing_rows(self.team) + [
            (self.player, "player", None),
            (make_user("p2"), "player", None),
        ]
        response = self.client.post(
            self.change_url(self.team), self.team_data(self.team, rows)
        )
        self.assertContains(response, FULL_MESSAGE)
        self.assertEqual(self.team.roster.count(), 1)

    def test_team_inline_replacing_a_player_on_a_full_roster_takes_two_saves(self):
        """Each row is checked against saved rows, so the delete has to save first."""
        leaving = Roster.objects.create(team=self.team, player=make_user("p1"))
        rows = self.existing_rows(self.team) + [(self.player, "player", None)]
        data = self.team_data(self.team, rows)
        data["roster-1-DELETE"] = "on"
        response = self.client.post(self.change_url(self.team), data)
        self.assertContains(response, FULL_MESSAGE)
        self.assertTrue(Roster.objects.filter(pk=leaving.pk).exists())
        self.assertFalse(self.team.roster.filter(player=self.player).exists())

    def test_team_inline_saves_a_change_that_keeps_both_rules(self):
        rows = self.existing_rows(self.team) + [(self.player, "player", None)]
        response = self.client.post(
            self.change_url(self.team), self.team_data(self.team, rows)
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.team.roster.count(), 2)

    def test_new_team_inline_rejects_a_second_team_in_the_season(self):
        Roster.objects.create(team=self.other, player=self.player)
        response = self.client.post(
            reverse("admin:teams_team_add"),
            self.team_data(rows=[(self.player, "player", None)]),
        )
        self.assertContains(response, OTHER_TEAM_MESSAGE)
        self.assertFalse(Team.objects.filter(name="New team").exists())

    def test_new_team_inline_rejects_more_rows_than_the_cap(self):
        rows = [(make_user(f"p{n}"), "player", None) for n in range(3)]
        response = self.client.post(
            reverse("admin:teams_team_add"), self.team_data(rows=rows)
        )
        self.assertContains(response, FULL_MESSAGE)
        self.assertFalse(Team.objects.filter(name="New team").exists())

    def test_team_admin_rejects_a_season_move_that_breaks_the_rule(self):
        target = make_season("Spring 2027")
        there = make_team(self.other_captain, name="There", season=target)
        Roster.objects.create(team=there, player=self.player)
        Roster.objects.create(team=self.team, player=self.player)
        response = self.client.post(
            self.change_url(self.team),
            self.team_data(self.team, self.existing_rows(self.team), season=target.pk),
        )
        self.assertContains(response, "already on another team in that season")
        self.team.refresh_from_db()
        self.assertEqual(self.team.season, self.season)


class ConcurrencySettingsTests(TestCase):
    @skipUnless(connection.vendor == "sqlite", "SQLite setting")
    def test_sqlite_transactions_take_the_write_lock_up_front(self):
        """Roster checks rely on this: SQLite ignores select_for_update."""
        self.assertEqual(
            connection.settings_dict["OPTIONS"]["transaction_mode"], "IMMEDIATE"
        )
