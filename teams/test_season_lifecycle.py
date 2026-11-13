"""Season lifecycle and League Admin controls (#107). Rules: docs/E2_CONTRACT.md."""

import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role

from .forms import FreeAgentRequestForm, TeamCreateForm
from .models import FreeAgentRequest, Roster, Season, Sport, Team
from .season_rules import SeasonAction, SeasonState

START = datetime.date(2026, 9, 1)


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


def make_admin(username="admin1"):
    user = make_user(username)
    assign_role(user, LEAGUE_ADMIN_ROLE)
    return user


def make_season(state=SeasonState.OPEN, name="Fall 2026"):
    return Season.objects.create(name=name, start_date=START, state=state)


def soccer():
    return Sport.objects.get_or_create(name="Soccer")[0]


def make_team(captain, season, name="Violets"):
    team = Team.objects.create(
        name=name, sport=soccer(), season=season, captain=captain
    )
    Roster.objects.create(team=team, player=captain, role=Roster.Role.CAPTAIN)
    return team


class SeasonModelTests(TestCase):
    def test_new_seasons_start_as_draft(self):
        season = Season.objects.create(name="Spring 2027", start_date=START)
        self.assertEqual(season.state, SeasonState.DRAFT)

    def test_move_to_follows_allowed_transitions(self):
        season = make_season(SeasonState.DRAFT)
        for target in (SeasonState.OPEN, SeasonState.ACTIVE, SeasonState.CLOSED):
            season.move_to(target)
            season.refresh_from_db()
            self.assertEqual(season.state, target)

    def test_open_season_can_go_back_to_draft(self):
        season = make_season(SeasonState.OPEN)
        season.move_to(SeasonState.DRAFT)
        self.assertEqual(Season.objects.get().state, SeasonState.DRAFT)

    def test_invalid_transitions_are_rejected_and_nothing_changes(self):
        cases = [
            (SeasonState.DRAFT, SeasonState.ACTIVE),
            (SeasonState.ACTIVE, SeasonState.OPEN),
            (SeasonState.CLOSED, SeasonState.OPEN),
            (SeasonState.OPEN, SeasonState.OPEN),
            (SeasonState.OPEN, "archived"),
        ]
        for current, target in cases:
            season = make_season(current, name=f"{current}-{target}")
            with self.assertRaises(ValidationError):
                season.move_to(target)
            season.refresh_from_db()
            self.assertEqual(season.state, current)

    def test_end_date_before_start_date_is_invalid(self):
        season = Season(
            name="Bad", start_date=START, end_date=START - datetime.timedelta(days=1)
        )
        with self.assertRaises(ValidationError):
            season.full_clean()

    def test_one_day_season_is_valid(self):
        Season(name="One day", start_date=START, end_date=START).full_clean()

    def test_allowing_and_visible_to_players(self):
        seasons = {
            state: make_season(state, name=state) for state in SeasonState.values
        }
        self.assertEqual(
            set(Season.objects.allowing(SeasonAction.CREATE_TEAM)),
            {seasons[SeasonState.OPEN]},
        )
        self.assertEqual(
            set(Season.objects.allowing(SeasonAction.REQUEST_FREE_AGENT)),
            {seasons[SeasonState.OPEN], seasons[SeasonState.ACTIVE]},
        )
        self.assertNotIn(
            seasons[SeasonState.DRAFT], Season.objects.visible_to_players()
        )
        self.assertEqual(Season.objects.visible_to_players().count(), 3)

    def test_team_without_season_allows_everything(self):
        team = make_team(make_user("cap"), None)
        for action in SeasonAction.values:
            self.assertTrue(team.allows(action))


class ManageSeasonsPermissionTests(TestCase):
    def setUp(self):
        self.season = make_season(SeasonState.DRAFT)
        self.urls = [
            ("get", reverse("teams:manage_seasons")),
            ("get", reverse("teams:create_season")),
            ("get", reverse("teams:edit_season", args=[self.season.pk])),
            ("post", reverse("teams:change_season_state", args=[self.season.pk])),
        ]

    def test_signed_out_users_are_sent_to_login(self):
        for method, url in self.urls:
            response = getattr(self.client, method)(url, {"state": "open"})
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response.url)

    def test_players_are_forbidden(self):
        self.client.force_login(make_user("player"))
        for method, url in self.urls:
            response = getattr(self.client, method)(url, {"state": "open"})
            self.assertEqual(response.status_code, 403)
        self.season.refresh_from_db()
        self.assertEqual(self.season.state, SeasonState.DRAFT)

    def test_superuser_and_league_admin_have_access(self):
        superuser = get_user_model().objects.create_superuser(
            "root", "root@nyu.edu", "pass12345!"
        )
        for user in (superuser, make_admin()):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("teams:manage_seasons")).status_code, 200
            )

    def test_state_change_requires_post(self):
        self.client.force_login(make_admin())
        url = reverse("teams:change_season_state", args=[self.season.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_league_setup_is_the_active_nav_item_on_seasons_pages(self):
        self.client.force_login(make_admin())
        for url in (reverse("teams:manage_seasons"), reverse("teams:create_season")):
            response = self.client.get(url)
            self.assertContains(response, 'aria-current="page"', count=1)
            self.assertContains(
                response,
                f'href="{reverse("teams:league_setup")}" aria-current="page"',
            )

    def test_seasons_is_not_a_top_level_nav_item(self):
        # #211: the seasons page is reached from League setup and the Overview.
        seasons_link = f'href="{reverse("teams:manage_seasons")}"'
        for user in (make_user("player"), make_admin()):
            self.client.force_login(user)
            self.assertNotContains(self.client.get(reverse("teams:list")), seasons_link)


class ManageSeasonsTests(TestCase):
    def setUp(self):
        self.client.force_login(make_admin())

    def test_create_season_starts_as_draft(self):
        response = self.client.post(
            reverse("teams:create_season"),
            {
                "name": "  Spring   2027 ",
                "start_date": "2027-01-20",
                "end_date": "2027-05-01",
                "max_roster_size": 10,
            },
            follow=True,
        )
        season = Season.objects.get()
        self.assertEqual(season.name, "Spring 2027")
        self.assertEqual(season.state, SeasonState.DRAFT)
        self.assertContains(response, "Created Spring 2027 as a draft.")

    def test_create_season_rejects_end_before_start(self):
        response = self.client.post(
            reverse("teams:create_season"),
            {
                "name": "Bad dates",
                "start_date": "2027-05-01",
                "end_date": "2027-01-20",
                "max_roster_size": 10,
            },
        )
        self.assertContains(
            response, "The end date can&#x27;t be before the start date."
        )
        self.assertFalse(Season.objects.exists())

    def test_edit_season_keeps_its_state(self):
        season = make_season(SeasonState.OPEN)
        self.client.post(
            reverse("teams:edit_season", args=[season.pk]),
            {"name": "Fall 2026 A", "start_date": "2026-09-01", "max_roster_size": 8},
        )
        season.refresh_from_db()
        self.assertEqual((season.name, season.max_roster_size), ("Fall 2026 A", 8))
        self.assertEqual(season.state, SeasonState.OPEN)

    def test_state_cannot_be_changed_through_the_edit_form(self):
        season = make_season(SeasonState.DRAFT)
        self.client.post(
            reverse("teams:edit_season", args=[season.pk]),
            {
                "name": "Fall 2026",
                "start_date": "2026-09-01",
                "max_roster_size": 12,
                "state": SeasonState.CLOSED,
            },
        )
        season.refresh_from_db()
        self.assertEqual(season.state, SeasonState.DRAFT)

    def test_closed_season_cannot_be_edited(self):
        season = make_season(SeasonState.CLOSED)
        response = self.client.get(reverse("teams:edit_season", args=[season.pk]))
        self.assertRedirects(response, reverse("teams:manage_seasons"))

    def test_list_offers_only_allowed_transitions(self):
        make_season(SeasonState.OPEN)
        response = self.client.get(reverse("teams:manage_seasons"))
        self.assertContains(response, "Start season")
        self.assertContains(response, "Move back to draft")
        self.assertNotContains(response, "Close season")
        self.assertNotContains(response, "Open registration")

    def test_list_empty_state(self):
        self.assertContains(
            self.client.get(reverse("teams:manage_seasons")), "No seasons yet"
        )

    def test_valid_state_change(self):
        season = make_season(SeasonState.DRAFT)
        response = self.client.post(
            reverse("teams:change_season_state", args=[season.pk]),
            {"state": SeasonState.OPEN},
            follow=True,
        )
        season.refresh_from_db()
        self.assertEqual(season.state, SeasonState.OPEN)
        self.assertContains(response, "Fall 2026 is now open.")

    def test_invalid_state_change_shows_error(self):
        season = make_season(SeasonState.CLOSED)
        response = self.client.post(
            reverse("teams:change_season_state", args=[season.pk]),
            {"state": SeasonState.OPEN},
            follow=True,
        )
        season.refresh_from_db()
        self.assertEqual(season.state, SeasonState.CLOSED)
        self.assertContains(response, "A season can&#x27;t move from Closed to Open.")

    def test_unknown_season_is_404(self):
        response = self.client.post(
            reverse("teams:change_season_state", args=[9999]), {"state": "open"}
        )
        self.assertEqual(response.status_code, 404)


class TeamCreationByStateTests(TestCase):
    def setUp(self):
        self.user = make_user("cap")
        self.client.force_login(self.user)

    def create(self, season):
        return self.client.post(
            reverse("teams:create"),
            {"name": "Violets", "sport": soccer().pk, "season": season.pk},
        )

    def test_only_open_seasons_are_offered(self):
        seasons = {
            state: make_season(state, name=state) for state in SeasonState.values
        }
        offered = set(TeamCreateForm(user=self.user).fields["season"].queryset)
        self.assertEqual(offered, {seasons[SeasonState.OPEN]})

    def test_open_season_accepts_a_team(self):
        self.create(make_season(SeasonState.OPEN))
        self.assertTrue(Team.objects.filter(name="Violets").exists())

    def test_other_states_reject_a_team(self):
        for state in (SeasonState.DRAFT, SeasonState.ACTIVE, SeasonState.CLOSED):
            response = self.create(make_season(state, name=state))
            self.assertEqual(response.status_code, 200)
        self.assertFalse(Team.objects.exists())

    def test_team_without_season_is_still_allowed(self):
        self.client.post(
            reverse("teams:create"), {"name": "Pickup", "sport": soccer().pk}
        )
        self.assertTrue(Team.objects.filter(name="Pickup", season=None).exists())


class RosterLockTests(TestCase):
    def setUp(self):
        self.captain = make_user("cap")
        self.player = make_user("player")
        self.newcomer = make_user("newcomer")
        self.season = make_season(SeasonState.OPEN)
        self.team = make_team(self.captain, self.season)
        self.entry = Roster.objects.create(team=self.team, player=self.player)

    def set_state(self, state):
        self.season.state = state
        self.season.save(update_fields=["state"])

    def add_newcomer(self):
        self.client.force_login(self.captain)
        return self.client.post(
            reverse("teams:add_player", args=[self.team.pk]),
            {"email": self.newcomer.email},
        )

    def remove_player(self):
        self.client.force_login(self.captain)
        return self.client.post(
            reverse("teams:remove_player", args=[self.team.pk, self.entry.pk])
        )

    def leave(self):
        self.client.force_login(self.player)
        return self.client.post(reverse("teams:leave", args=[self.team.pk]))

    def test_open_season_allows_add_remove_and_leave(self):
        self.add_newcomer()
        self.assertTrue(self.team.roster.filter(player=self.newcomer).exists())
        self.remove_player()
        self.assertFalse(self.team.roster.filter(player=self.player).exists())

    def test_player_can_leave_in_open_season(self):
        self.leave()
        self.assertFalse(self.team.roster.filter(player=self.player).exists())

    def test_active_season_allows_adding_but_locks_leaving_and_removal(self):
        self.set_state(SeasonState.ACTIVE)
        self.add_newcomer()
        self.assertTrue(self.team.roster.filter(player=self.newcomer).exists())

        response = self.remove_player()
        self.assertRedirects(response, reverse("teams:detail", args=[self.team.pk]))
        self.assertTrue(self.team.roster.filter(player=self.player).exists())

        self.leave()
        self.assertTrue(self.team.roster.filter(player=self.player).exists())

    def test_closed_season_blocks_every_roster_change(self):
        self.set_state(SeasonState.CLOSED)
        self.add_newcomer()
        self.remove_player()
        self.leave()
        self.assertEqual(
            set(self.team.roster.values_list("player__username", flat=True)),
            {"cap", "player"},
        )

    def test_add_player_page_redirects_when_season_is_closed(self):
        self.set_state(SeasonState.CLOSED)
        self.client.force_login(self.captain)
        response = self.client.get(reverse("teams:add_player", args=[self.team.pk]))
        self.assertRedirects(response, reverse("teams:detail", args=[self.team.pk]))

    def test_team_page_explains_locked_roster(self):
        self.set_state(SeasonState.ACTIVE)
        self.client.force_login(self.player)
        response = self.client.get(reverse("teams:detail", args=[self.team.pk]))
        self.assertContains(response, "Rosters are locked once the season starts.")
        self.assertNotContains(response, reverse("teams:leave", args=[self.team.pk]))
        self.client.force_login(self.captain)
        response = self.client.get(reverse("teams:detail", args=[self.team.pk]))
        self.assertNotContains(
            response, reverse("teams:remove_player", args=[self.team.pk, self.entry.pk])
        )
        self.assertContains(response, "Active")

    def test_team_page_shows_roster_closed_for_closed_season(self):
        self.set_state(SeasonState.CLOSED)
        self.client.force_login(self.captain)
        response = self.client.get(reverse("teams:detail", args=[self.team.pk]))
        self.assertContains(response, "Roster closed")

    def test_teams_without_a_season_are_not_locked(self):
        team = make_team(self.captain, None, name="Pickup")
        Roster.objects.create(team=team, player=self.newcomer)
        self.client.force_login(self.newcomer)
        self.client.post(reverse("teams:leave", args=[team.pk]))
        self.assertFalse(team.roster.filter(player=self.newcomer).exists())


class FreeAgentByStateTests(TestCase):
    def setUp(self):
        self.player = make_user("player")
        self.client.force_login(self.player)

    def test_requests_are_offered_in_open_and_active_seasons_only(self):
        seasons = {
            state: make_season(state, name=state) for state in SeasonState.values
        }
        offered = set(FreeAgentRequestForm(user=self.player).fields["season"].queryset)
        self.assertEqual(
            offered, {seasons[SeasonState.OPEN], seasons[SeasonState.ACTIVE]}
        )

    def test_draft_season_request_is_rejected(self):
        season = make_season(SeasonState.DRAFT)
        self.client.post(
            reverse("teams:free_agent_pool"),
            {"season": season.pk, "sport": soccer().pk},
        )
        self.assertFalse(FreeAgentRequest.objects.exists())

    def test_active_season_accepts_a_request(self):
        season = make_season(SeasonState.ACTIVE)
        self.client.post(
            reverse("teams:free_agent_pool"),
            {"season": season.pk, "sport": soccer().pk},
        )
        self.assertTrue(FreeAgentRequest.objects.filter(season=season).exists())

    def test_cancel_allowed_in_active_but_not_closed(self):
        season = make_season(SeasonState.ACTIVE)
        request = FreeAgentRequest.objects.create(
            player=self.player, season=season, sport=soccer()
        )
        url = reverse("teams:cancel_free_agent_request", args=[request.pk])

        season.state = SeasonState.CLOSED
        season.save(update_fields=["state"])
        response = self.client.post(url, follow=True)
        self.assertTrue(FreeAgentRequest.objects.filter(pk=request.pk).exists())
        self.assertContains(response, "is closed, so requests can&#x27;t be changed.")

        season.state = SeasonState.ACTIVE
        season.save(update_fields=["state"])
        self.client.post(url)
        self.assertFalse(FreeAgentRequest.objects.filter(pk=request.pk).exists())


class AdminMatchingByStateTests(TestCase):
    def setUp(self):
        self.client.force_login(make_admin())

    def test_manage_page_lists_open_and_active_seasons_only(self):
        for state in SeasonState.values:
            make_season(state, name=f"Season {state}")
        response = self.client.get(reverse("teams:manage_free_agents"))
        self.assertContains(response, "Season open")
        self.assertContains(response, "Season active")
        self.assertNotContains(response, "Season draft")
        self.assertNotContains(response, "Season closed")

    def test_closed_season_cannot_be_managed_or_matched(self):
        season = make_season(SeasonState.CLOSED)
        self.assertEqual(
            self.client.get(
                reverse("teams:manage_season_free_agents", args=[season.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("teams:match_free_agents", args=[season.pk])
            ).status_code,
            404,
        )

    def test_matching_works_in_an_active_season(self):
        season = make_season(SeasonState.ACTIVE)
        team = make_team(make_user("cap"), season)
        player = make_user("agent")
        FreeAgentRequest.objects.create(player=player, season=season, sport=soccer())
        self.client.post(reverse("teams:match_free_agents", args=[season.pk]))
        self.assertTrue(team.roster.filter(player=player).exists())


class SeasonStateMigrationTests(TransactionTestCase):
    """0010 turns is_active into state: True becomes open, False becomes closed."""

    migrate_from = [("teams", "0009_merge_20261102_1821")]
    migrate_to = [("teams", "0010_season_state")]

    def test_is_active_is_converted_to_state(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldSeason = old_apps.get_model("teams", "Season")
        running = OldSeason.objects.create(
            name="Running", start_date=START, is_active=True
        )
        finished = OldSeason.objects.create(
            name="Finished", start_date=START, is_active=False
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        NewSeason = new_apps.get_model("teams", "Season")
        self.assertEqual(NewSeason.objects.get(pk=running.pk).state, "open")
        self.assertEqual(NewSeason.objects.get(pk=finished.pk).state, "closed")

        # Leave the database on the latest migration for the other tests.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
