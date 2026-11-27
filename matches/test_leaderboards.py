"""Player leaderboards (#311): ranking, filters, visibility and opt-out."""

import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from profiles.forms import ProfileForm
from profiles.models import PlayerProfile
from teams.models import EventType, Roster, Season, Team
from teams.season_rules import SeasonState

from .leaderboards import MIN_GAMES_FOR_PER_GAME, player_leaderboards
from .models import Match, MatchAppearance, PlayerStat
from .tests import MatchFixtures, at, make_user

URL = reverse("matches:player_leaders")


def named(username, first, last):
    user = make_user(username)
    user.first_name, user.last_name = first, last
    user.save()
    return user


class LeaderboardFixtures(MatchFixtures):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.goal = EventType.objects.create(
            sport=cls.soccer, name="Goal", is_scoring=True
        )
        cls.assist = EventType.objects.create(sport=cls.soccer, name="Assist")
        cls.points = EventType.objects.create(sport=cls.hoops, name="Points")
        cls.alex = named("alex", "Alex", "Lee")
        cls.sam = named("sam", "Sam", "Kim")
        cls.jo = named("jo", "Jo", "Park")
        cls.day = 1

    def play(self, stats, *, season=None, home=None, away=None, **match_fields):
        """A scored match. stats: {player: (team, {event type: value})}.

        Every player in stats gets an appearance.
        """
        start = at(1, 9) + datetime.timedelta(days=self.day)
        self.day += 1
        values = dict(
            season=season or self.season,
            home_team=home or self.home,
            away_team=away or self.away,
            facility=self.field,
            starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
            home_score=1,
            away_score=0,
        )
        values.update(match_fields)
        match = Match.objects.create(**values)
        for player, (team, values_by_type) in stats.items():
            MatchAppearance.objects.create(match=match, team=team, player=player)
            for event_type, value in values_by_type.items():
                PlayerStat.objects.create(
                    match=match,
                    team=team,
                    player=player,
                    event_type=event_type,
                    value=value,
                )
        return match

    def boards(self, user=None, sport=None, season=None):
        return {
            board.event_type.name: board.rows
            for board in player_leaderboards(
                user or self.player, sport or self.soccer, season
            )
        }

    def summary(self, rows):
        return [(r.rank, r.player.username, r.total, r.games) for r in rows]

    def get(self, user=None, **params):
        self.client.force_login(user or self.player)
        return self.client.get(URL, params)


class RankingTests(LeaderboardFixtures):
    def test_scoring_stat_comes_first(self):
        self.play({self.alex: (self.home, {self.goal: 1})})
        boards = player_leaderboards(self.player, self.soccer)
        self.assertEqual([b.event_type for b in boards], [self.goal, self.assist])

    def test_ranks_by_total_with_shared_ranks(self):
        self.play(
            {
                self.alex: (self.home, {self.goal: 3}),
                self.sam: (self.home, {self.goal: 2}),
                self.jo: (self.away, {self.goal: 2}),
            }
        )
        self.play({self.alex: (self.home, {self.goal: 1})})
        rows = self.boards()["Goal"]
        # Jo Park and Sam Kim tie on 2 and sort by last name.
        self.assertEqual(
            self.summary(rows),
            [(1, "alex", 4, 2), (2, "jo", 2, 1), (2, "sam", 2, 1)],
        )

    def test_zero_totals_are_left_out(self):
        self.play({self.alex: (self.home, {self.goal: 0, self.assist: 2})})
        boards = self.boards()
        self.assertEqual(boards["Goal"], [])
        self.assertEqual(self.summary(boards["Assist"]), [(1, "alex", 2, 1)])

    def test_per_game_needs_the_minimum_games(self):
        for _ in range(MIN_GAMES_FOR_PER_GAME - 1):
            self.play({self.alex: (self.home, {self.goal: 1})})
        self.assertIsNone(self.boards()["Goal"][0].per_game)
        self.play({self.alex: (self.home, {self.goal: 2})})
        self.assertEqual(self.boards()["Goal"][0].per_game, 1.3)

    def test_per_game_breaks_a_tie_on_total(self):
        for _ in range(3):
            self.play({self.alex: (self.home, {self.goal: 2})})
        for _ in range(3):
            self.play({self.jo: (self.away, {self.goal: 1})})
        self.play({self.jo: (self.away, {self.goal: 3})})
        # Both have 6 goals: Alex in 3 games (2.0), Jo in 4 (1.5).
        rows = self.boards()["Goal"]
        self.assertEqual([r.player for r in rows], [self.alex, self.jo])
        self.assertEqual([r.rank for r in rows], [1, 1])

    def test_team_is_the_latest_one(self):
        other = Team.objects.create(
            name="Torches", sport=self.soccer, season=self.season, captain=self.player
        )
        self.play({self.alex: (self.home, {self.goal: 1})})
        self.play({self.alex: (other, {self.goal: 1})}, home=other)
        self.assertEqual(self.boards()["Goal"][0].team, other)

    def test_limit(self):
        self.play({self.alex: (self.home, {self.goal: 2})})
        self.play({self.sam: (self.home, {self.goal: 1})})
        rows = player_leaderboards(self.player, self.soccer, limit=1)[0].rows
        self.assertEqual([r.player for r in rows], [self.alex])

    def test_sport_without_event_types_has_no_boards(self):
        volleyball = type(self.soccer).objects.create(name="Volleyball")
        self.assertEqual(player_leaderboards(self.player, volleyball), [])


class WhatCountsTests(LeaderboardFixtures):
    def test_only_counted_matches(self):
        self.play({self.alex: (self.home, {self.goal: 5})}, status="cancelled")
        self.play({self.sam: (self.home, {self.goal: 4})}, home_score=None)
        self.play({self.jo: (self.away, {self.goal: 1})})
        self.assertEqual(self.summary(self.boards()["Goal"]), [(1, "jo", 1, 1)])

    def test_other_sports_do_not_count(self):
        self.play(
            {self.alex: (self.hoops_team, {self.points: 9})},
            home=self.hoops_team,
            away=Team.objects.create(
                name="Dunkers",
                sport=self.hoops,
                season=self.season,
                captain=self.player,
            ),
        )
        self.assertEqual(self.boards(), {"Goal": [], "Assist": []})
        self.assertEqual(
            self.summary(self.boards(sport=self.hoops)["Points"]),
            [(1, "alex", 9, 1)],
        )

    def test_draft_seasons_count_only_for_league_admins(self):
        draft = Season.objects.create(
            name="Draft", start_date=datetime.date(2027, 3, 1), state=SeasonState.DRAFT
        )
        self.play({self.alex: (self.home, {self.goal: 2})}, season=draft)
        self.assertEqual(self.boards()["Goal"], [])
        self.assertEqual(len(self.boards(user=self.admin)["Goal"]), 1)

    def test_season_filter(self):
        self.play({self.alex: (self.home, {self.goal: 2})})
        self.play({self.alex: (self.home, {self.goal: 3})}, season=self.other_season)
        self.assertEqual(self.boards(season=self.season)["Goal"][0].total, 2)
        self.assertEqual(self.boards()["Goal"][0].total, 5)

    def test_opted_out_players_are_left_out(self):
        self.play(
            {
                self.alex: (self.home, {self.goal: 2}),
                self.sam: (self.home, {self.goal: 1}),
            }
        )
        PlayerProfile.objects.create(user=self.alex, show_on_leaderboards=False)
        PlayerProfile.objects.create(user=self.sam)
        self.assertEqual(self.summary(self.boards()["Goal"]), [(1, "sam", 1, 1)])

    def test_query_count_is_fixed(self):
        self.play({self.alex: (self.home, {self.goal: 1})})
        with CaptureQueriesContext(connection) as captured:
            player_leaderboards(self.player, self.soccer)
        for i in range(6):
            fan = named(f"fan{i}", "Fan", str(i))
            Roster.objects.create(team=self.away, player=fan)
            self.play(
                {
                    fan: (self.away, {self.goal: i + 1, self.assist: 1}),
                    self.alex: (self.home, {self.assist: 2}),
                }
            )
        with self.assertNumQueries(len(captured)):
            player_leaderboards(self.player, self.soccer)


class PageTests(LeaderboardFixtures):
    def test_anonymous_redirects_to_login(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_page_shows_the_boards(self):
        self.play({self.alex: (self.home, {self.goal: 2, self.assist: 1})})
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sport"], self.soccer)
        self.assertEqual(response.context["season"], self.season)
        self.assertEqual(response.context["nav_section"], "schedule")
        self.assertContains(response, "Player leaders")
        self.assertContains(response, 'id="leaders-tab-%d"' % self.goal.pk)
        self.assertContains(response, 'id="leaders-tab-%d"' % self.assist.pk)
        self.assertContains(response, "Alex Lee")
        self.assertContains(response, reverse("profiles:detail", args=[self.alex.pk]))
        self.assertContains(response, reverse("teams:detail", args=[self.home.pk]))
        self.assertContains(response, "No Goal recorded yet", count=0)

    def test_viewer_row_is_highlighted(self):
        self.play({self.player: (self.home, {self.goal: 1})})
        response = self.get()
        self.assertContains(response, 'class="pn-row-me"')
        self.assertContains(response, "(you)")

    def test_inactive_player_has_no_profile_link(self):
        self.play({self.alex: (self.home, {self.goal: 1})})
        self.alex.is_active = False
        self.alex.save()
        response = self.get()
        self.assertContains(response, "Alex Lee")
        self.assertNotContains(
            response, reverse("profiles:detail", args=[self.alex.pk])
        )

    def test_default_sport_is_the_viewers_team_sport(self):
        self.play({self.sam: (self.home, {self.goal: 1})})
        Roster.objects.create(team=self.hoops_team, player=self.alex)
        self.assertEqual(self.get(self.alex).context["sport"], self.hoops)
        self.assertEqual(
            self.get(self.alex, sport=self.soccer.pk).context["sport"], self.soccer
        )

    def test_default_sport_without_a_team_has_the_latest_result(self):
        self.play({self.sam: (self.home, {self.goal: 1})})
        self.assertEqual(self.get().context["sport"], self.soccer)

    def test_default_sport_with_no_results_is_first_by_name(self):
        self.assertEqual(self.get().context["sport"], self.hoops)

    def test_unknown_sport_falls_back(self):
        self.assertEqual(self.get(sport="999").context["sport"], self.hoops)
        self.assertEqual(self.get(sport="x").context["sport"], self.hoops)

    def test_default_season_is_the_newest_with_results(self):
        self.play({self.alex: (self.home, {self.goal: 1})})
        self.play({self.alex: (self.home, {self.goal: 1})}, season=self.other_season)
        response = self.get(sport=self.soccer.pk)
        self.assertEqual(response.context["season"], self.other_season)
        self.assertEqual(response.context["seasons"], [self.other_season, self.season])

    def test_all_seasons_and_bad_season_values(self):
        self.play({self.alex: (self.home, {self.goal: 1})})
        response = self.get(sport=self.soccer.pk, season="all")
        self.assertIsNone(response.context["season"])
        self.assertContains(response, "All seasons")
        response = self.get(sport=self.soccer.pk, season="999")
        self.assertEqual(response.context["season"], self.season)

    def test_season_link_picks_the_seasons_sport(self):
        hoops_season = Season.objects.create(
            name="Hoops fall",
            start_date=datetime.date(2026, 9, 2),
            state=SeasonState.OPEN,
            sport=self.hoops,
        )
        response = self.get(season=hoops_season.pk)
        self.assertEqual(response.context["sport"], self.hoops)

    def test_no_sports_shows_the_empty_state(self):
        EventType.objects.all().delete()
        response = self.get()
        self.assertIsNone(response.context["sport"])
        self.assertContains(response, "No stats yet")

    def test_empty_board_shows_its_empty_state(self):
        response = self.get(sport=self.soccer.pk)
        self.assertContains(response, "No Goal recorded yet")
        self.assertContains(response, "No Assist recorded yet")

    def test_standings_pages_link_here(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse("matches:standings"))
        self.assertContains(response, URL)
        response = self.client.get(
            reverse("matches:season_standings", args=[self.season.pk])
        )
        self.assertContains(response, f"{URL}?season={self.season.pk}")


class OptOutFormTests(LeaderboardFixtures):
    def data(self, **overrides):
        values = {
            "first_name": "Alex",
            "last_name": "Lee",
            "n_number": "N12345678",
            "net_id": "al1234",
        }
        values.update(overrides)
        return values

    def test_profiles_show_by_default(self):
        self.assertTrue(
            PlayerProfile.objects.create(user=self.alex).show_on_leaderboards
        )

    def test_unticking_the_box_opts_out(self):
        profile = PlayerProfile(user=self.alex)
        form = ProfileForm(self.data(), instance=profile, user=self.alex)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertFalse(PlayerProfile.objects.get(user=self.alex).show_on_leaderboards)

    def test_ticking_the_box_opts_in(self):
        profile = PlayerProfile(user=self.alex)
        form = ProfileForm(
            self.data(show_on_leaderboards="on"), instance=profile, user=self.alex
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertTrue(PlayerProfile.objects.get(user=self.alex).show_on_leaderboards)
        self.assertIn("show_on_leaderboards", form.fields)
        self.assertEqual(
            str(form.fields["show_on_leaderboards"].label), "Show me on leaderboards"
        )
