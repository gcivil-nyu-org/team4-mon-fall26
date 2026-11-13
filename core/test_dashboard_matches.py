"""The dashboard's stat row, upcoming matches panel and team records (#199)."""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from matches.schedule import player_schedule
from matches.standings import player_record, team_records
from matches.test_schedule import ScheduleFixtures
from notifications.models import Notification
from teams.models import Roster

URL = reverse("core:home")
EMPTY_PANEL = (
    "Your schedule appears once a League Admin schedules your team.",
    "No upcoming matches",
)


class DashboardMatchFixtures(ScheduleFixtures):
    """The player is on Violets (`home`), which plays Bobcats (`away`)."""

    def add_result(self, home_score, away_score, start=-48, **overrides):
        return self.add_match(
            start=start, home_score=home_score, away_score=away_score, **overrides
        )

    def add_strangers_match(self, **overrides):
        """A match in the player's season between two teams they aren't on."""
        return self.add_match(home_team=self.away, away_team=self.third, **overrides)

    def get(self):
        return self.client.get(URL)


class PlayerScheduleTests(DashboardMatchFixtures):
    def test_upcoming_nearest_first_and_past_most_recent_first(self):
        later = self.add_match(start=48)
        sooner = self.add_match(start=24)
        old = self.add_match(start=-72)
        recent = self.add_match(start=-24)
        upcoming, past = player_schedule(self.player)
        self.assertEqual(upcoming, [sooner, later])
        self.assertEqual(past, [recent, old])

    def test_match_being_played_is_upcoming(self):
        live = self.add_match(start=-1, length=2)
        self.assertEqual(player_schedule(self.player), ([live], []))

    def test_cancelled_matches_stay(self):
        match = self.add_match()
        match.cancel()
        self.assertEqual(player_schedule(self.player)[0], [match])

    def test_covers_every_team_of_the_player(self):
        Roster.objects.create(team=self.outsider, player=self.player)
        fall = self.add_match(start=24)
        spring = self.add_other_season_match()
        self.assertEqual(player_schedule(self.player)[0], [spring, fall])

    def test_other_teams_matches_are_left_out(self):
        self.add_strangers_match()
        self.add_other_season_match()
        self.assertEqual(player_schedule(self.player), ([], []))

    def test_no_teams_means_no_matches(self):
        self.add_match()
        self.assertEqual(player_schedule(self.admin), ([], []))

    def test_draft_season_hidden_from_players_but_not_league_admins(self):
        match = self.add_match()
        self.make_draft()
        self.assertEqual(player_schedule(self.player), ([], []))
        assign_role(self.player, LEAGUE_ADMIN_ROLE)
        self.assertEqual(player_schedule(self.player)[0], [match])

    def test_opponent_is_the_team_the_player_is_not_on(self):
        self.add_match(start=24)
        self.add_match(start=48, home_team=self.third, away_team=self.home)
        upcoming, _ = player_schedule(self.player)
        self.assertEqual([m.opponent for m in upcoming], [self.away, self.third])

    def test_query_count_does_not_grow_with_matches(self):
        for start in (24, 48, 72, -24, -48):
            self.add_match(start=start)
        with self.assertNumQueries(3):  # roster, League Admin role, matches
            player_schedule(self.player)


class RecordTests(DashboardMatchFixtures):
    def test_counts_wins_draws_and_losses_home_and_away(self):
        self.add_result(2, 1)
        self.add_result(1, 1)
        self.add_result(0, 3)
        self.add_result(0, 1, home_team=self.third, away_team=self.home)
        self.assertEqual(
            player_record([self.home.pk]),
            {"played": 4, "won": 2, "drawn": 1, "lost": 1},
        )

    def test_cancelled_and_unscored_matches_do_not_count(self):
        self.add_match(start=-24)
        cancelled = self.add_result(5, 0)
        cancelled.cancel()
        self.add_match(start=-72, home_score=1)
        self.assertEqual(
            player_record([self.home.pk]),
            {"played": 0, "won": 0, "drawn": 0, "lost": 0},
        )

    def test_other_teams_results_do_not_count(self):
        self.add_result(4, 0, home_team=self.away, away_team=self.third)
        self.assertEqual(player_record([self.home.pk])["played"], 0)

    def test_sums_all_teams_and_seasons(self):
        self.add_result(2, 0)
        self.add_result(
            1,
            3,
            season=self.other_season,
            home_team=self.outsider,
            away_team=self.make_team("Rivals", self.soccer, self.other_season),
        )
        self.assertEqual(
            player_record([self.home.pk, self.outsider.pk]),
            {"played": 2, "won": 1, "drawn": 0, "lost": 1},
        )

    def test_team_records_are_per_team_in_one_query(self):
        self.add_result(2, 0)
        self.add_result(1, 1, home_team=self.third, away_team=self.away)
        with self.assertNumQueries(1):
            records = team_records([self.home.pk, self.away.pk, self.hoops_team.pk])
        self.assertEqual(
            records[self.home.pk], {"played": 1, "won": 1, "drawn": 0, "lost": 0}
        )
        self.assertEqual(
            records[self.away.pk], {"played": 2, "won": 0, "drawn": 1, "lost": 1}
        )
        self.assertEqual(records[self.hoops_team.pk]["played"], 0)

    def test_no_teams_runs_no_query(self):
        with self.assertNumQueries(0):
            self.assertEqual(player_record([])["played"], 0)


class StatRowTests(DashboardMatchFixtures):
    def test_old_cards_are_gone(self):
        response = self.get()
        for text in ("Captain of", "Teammates</div>", "coming soon"):
            self.assertNotContains(response, text)
        for label in ("Next match", "Record", "Games played", "Unread"):
            self.assertContains(response, f'<div class="subheader">{label}</div>')

    def test_no_results_shows_zeros_and_helpful_text(self):
        Notification.objects.filter(recipient=self.player).delete()
        response = self.get()
        self.assertIsNone(response.context["next_match"])
        self.assertContains(response, "Nothing scheduled")
        self.assertContains(response, '<div class="h1 mb-0 pn-num">0–0–0</div>')
        self.assertContains(response, "No results yet")
        self.assertContains(response, '<div class="h1 mb-0 pn-num">0</div>', 2)
        self.assertContains(response, "All caught up")
        self.assertNotContains(response, "to play")

    def test_next_match_is_the_nearest_uncancelled_one(self):
        self.add_match(start=24).cancel()
        nearest = self.add_match(start=48, home_team=self.third, away_team=self.home)
        self.add_match(start=72)
        response = self.get()
        self.assertEqual(response.context["next_match"], nearest)
        self.assertContains(response, "vs Terriers")
        local = timezone.localtime(nearest.starts_at)
        self.assertContains(response, local.strftime("%a %b ") + str(local.day))
        self.assertNotContains(response, "Nothing scheduled")

    def test_record_and_games_played_cover_all_teams(self):
        Roster.objects.create(team=self.outsider, player=self.player)
        self.add_result(2, 0)
        self.add_result(1, 1, start=-72)
        self.add_result(
            0,
            1,
            season=self.other_season,
            home_team=self.outsider,
            away_team=self.make_team("Rivals", self.soccer, self.other_season),
        )
        self.add_match(start=24)
        self.add_match(start=48).cancel()
        response = self.get()
        self.assertEqual(
            response.context["record"],
            {"played": 3, "won": 1, "drawn": 1, "lost": 1},
        )
        self.assertContains(response, '<div class="h1 mb-0 pn-num">1–1–1</div>')
        self.assertContains(response, '<div class="h1 mb-0 pn-num">3</div>')
        self.assertContains(response, '<span class="pn-num">1</span> to play')
        self.assertNotContains(response, "No results yet")

    def test_unread_counts_only_my_unread_notifications(self):
        Notification.objects.filter(recipient=self.player).delete()
        for _ in range(2):
            Notification.objects.create(recipient=self.player, verb="Unread")
        Notification.objects.create(recipient=self.player, verb="Read", is_read=True)
        Notification.objects.create(recipient=self.admin, verb="Not mine")
        response = self.get()
        self.assertContains(response, '<div class="h1 mb-0 pn-num">2</div>')
        self.assertContains(response, "Notifications to read")
        self.assertNotContains(response, "All caught up")
        self.assertContains(
            response,
            f'<a class="card card-sm card-link card-link-pop h-100" '
            f'href="{reverse("notifications:list")}">',
        )


class UpcomingPanelTests(DashboardMatchFixtures):
    def panel(self, response):
        html = response.content.decode()
        after = html.split('<h3 class="card-title">Upcoming matches</h3>')[1]
        return after.split('<h3 class="card-title">Standings</h3>')[0]

    def test_empty_state(self):
        response = self.get()
        for text in EMPTY_PANEL:
            self.assertContains(response, text)
        self.assertNotContains(response, "Recent results")
        self.assertContains(response, reverse("matches:schedule_seasons"))

    def test_shows_at_most_five_upcoming_nearest_first(self):
        for day in range(1, 8):
            self.add_match(start=24 * day)
        panel = self.panel(self.get())
        self.assertEqual(panel.count("list-group-item"), 5)
        self.assertNotIn(EMPTY_PANEL[0], panel)

    def test_cancelled_upcoming_match_keeps_its_badge(self):
        self.add_match().cancel()
        panel = self.panel(self.get())
        self.assertEqual(panel.count("list-group-item"), 1)
        self.assertIn("Cancelled", panel)

    def test_last_three_results_most_recent_first(self):
        for day in range(1, 5):
            self.add_result(day, 0, start=-24 * day)
        self.add_match(start=-1000)
        panel = self.panel(self.get())
        self.assertIn("Recent results", panel)
        self.assertIn(EMPTY_PANEL[0], panel)
        self.assertEqual(panel.count("list-group-item"), 3)
        scores = [panel.index(f"{day} – 0") for day in (1, 2, 3)]
        self.assertEqual(scores, sorted(scores))
        self.assertNotIn("4 – 0", panel)

    def test_other_teams_matches_never_appear(self):
        self.add_strangers_match()
        self.add_strangers_match(start=-48, home_score=9, away_score=8)
        self.add_other_season_match()
        response = self.get()
        self.assertContains(response, EMPTY_PANEL[0])
        self.assertNotContains(response, "Recent results")
        self.assertNotContains(response, "Outsiders")
        self.assertIsNone(response.context["next_match"])
        self.assertEqual(response.context["record"]["played"], 0)

    def test_draft_season_matches_never_appear(self):
        self.add_match()
        self.add_match(start=-48)
        self.make_draft()
        response = self.get()
        self.assertContains(response, EMPTY_PANEL[0])
        self.assertContains(response, "Nothing scheduled")
        self.assertEqual(response.context["upcoming_matches"], [])
        self.assertEqual(response.context["past_matches"], [])


class MyTeamsRowTests(DashboardMatchFixtures):
    def test_rows_show_each_teams_record_and_a_chat_link(self):
        Roster.objects.create(team=self.outsider, player=self.player)
        self.add_result(3, 1)
        self.add_result(2, 2, start=-72)
        response = self.get()
        records = {e.team: e.record for e in response.context["entries"]}
        self.assertEqual(
            records[self.home], {"played": 2, "won": 1, "drawn": 1, "lost": 0}
        )
        self.assertEqual(records[self.outsider]["played"], 0)
        self.assertContains(response, "1–1–0<span")
        self.assertContains(response, "0–0–0<span")
        for team in (self.home, self.outsider):
            self.assertContains(
                response,
                f'href="{reverse("chat:thread", args=[team.pk])}" '
                f'aria-label="Team chat"',
            )


class DashboardQueryCountTests(DashboardMatchFixtures):
    """Guards the panels against per-row queries."""

    def count_queries(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.get().status_code, 200)
        return len(queries)

    def test_queries_do_not_grow_with_teams_and_matches(self):
        self.add_match(start=24)
        self.add_result(1, 0)
        baseline = self.count_queries()
        Roster.objects.create(team=self.outsider, player=self.player)
        self.add_other_season_match()
        for day in range(2, 7):
            self.add_match(start=24 * day)
            self.add_result(day, 0, start=-24 * day)
        self.assertEqual(self.count_queries(), baseline)

    def test_upper_bound(self):
        Roster.objects.create(team=self.outsider, player=self.player)
        for day in range(1, 7):
            self.add_match(start=24 * day)
            self.add_result(day, 0, start=-24 * day)
        self.assertLessEqual(self.count_queries(), 25)
