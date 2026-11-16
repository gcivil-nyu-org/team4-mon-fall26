"""The schedule table at /matches/schedule/ (#250)."""

from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from facilities.models import Facility
from teams.models import Division, EventType, Roster, Sport

from .models import MatchPeriodScore, PlayerStat
from .schedule import SCHEDULE_PER_PAGE
from .test_match_detail import LinkCollector
from .test_match_sheet import named_user
from .test_schedule import ScheduleFixtures
from .tests import make_user

URL = reverse("matches:schedule")
BAD_VALUES = ("abc", "-1", "1.5", "999999", "9" * 40, "\x00", " ")


def query(href):
    """The query params of a link, as {name: [values]}."""
    return parse_qs(urlsplit(href.replace("&amp;", "&")).query)


class TableFixtures(ScheduleFixtures):
    def get(self, user=None, **params):
        if user:
            self.client.force_login(user)
        return self.client.get(URL, params)

    def rows(self, **params):
        return list(self.get(**params).context["matches"])

    def links(self, response):
        parser = LinkCollector()
        parser.feed(response.content.decode())
        return parser


class PageTests(TableFixtures):
    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_is_in_the_nav(self):
        response = self.get()
        self.assertContains(response, f'href="{URL}" aria-current="page"')
        self.assertEqual(response.context["nav_section"], "schedule")

    def test_every_season_in_one_table(self):
        here = self.add_match(start=24)
        there = self.add_other_season_match()
        self.assertEqual(self.rows(), [there, here])

    def test_empty_states(self):
        self.assertContains(self.get(), "No upcoming matches")
        self.assertContains(self.get(tab="results"), "No results yet")
        self.add_match()
        response = self.get(tab="results", season=self.season.pk)
        self.assertContains(response, "No matches match these filters.")
        self.assertContains(response, "Clear filters")

    def test_no_email_on_the_page(self):
        match = self.add_match(start=-24, home_score=2, away_score=1)
        scorer = named_user("scorer@nyu.edu", "", "")
        Roster.objects.create(team=self.home, player=scorer)
        goal = EventType.objects.create(sport=self.soccer, name="Goal")
        PlayerStat.objects.create(
            match=match, player=scorer, team=self.home, event_type=goal, value=2
        )
        for user in (self.player, self.admin):
            for tab in ("upcoming", "results", "all"):
                response = self.get(user, tab=tab)
                self.assertNotContains(response, "@nyu.edu")
        self.assertContains(self.get(tab="results"), "PlayNYU player")


class VisibilityTests(TableFixtures):
    def test_players_do_not_see_draft_seasons(self):
        draft_match = self.add_match()
        other = self.add_other_season_match()
        self.make_draft()
        response = self.get(tab="all")
        self.assertEqual(list(response.context["matches"]), [other])
        seasons = list(response.context["form"].fields["season"].queryset)
        self.assertNotIn(self.season, seasons)
        self.assertIn(self.other_season, seasons)
        # Asking for the draft season by id shows nothing of it.
        response = self.get(tab="all", season=self.season.pk)
        self.assertNotIn(draft_match, response.context["matches"])
        response = self.get(tab="all", team=self.home.pk)
        self.assertNotIn(draft_match, response.context["matches"])

    def test_league_admins_and_superusers_see_draft_seasons(self):
        draft_match = self.add_match()
        self.make_draft()
        root = make_user("root")
        root.is_superuser = True
        root.save()
        for user in (self.admin, root):
            response = self.get(user, tab="all", season=self.season.pk)
            self.assertEqual(list(response.context["matches"]), [draft_match])
            self.assertIn(
                self.season, response.context["form"].fields["season"].queryset
            )


class TabTests(TableFixtures):
    def setUp(self):
        super().setUp()
        self.old = self.add_match(start=-48)
        self.recent = self.add_match(start=-24)
        self.playing = self.add_match(start=-1, length=2)
        self.soon = self.add_match(start=24)
        self.later = self.add_match(start=48)

    def test_upcoming_is_the_default_soonest_first(self):
        expected = [self.playing, self.soon, self.later]
        self.assertEqual(self.rows(), expected)
        self.assertEqual(self.rows(tab="upcoming"), expected)
        self.assertEqual(self.get().context["sort"], "date")

    def test_results_newest_first(self):
        self.assertEqual(self.rows(tab="results"), [self.recent, self.old])
        self.assertEqual(self.get(tab="results").context["sort"], "-date")

    def test_all_oldest_first(self):
        self.assertEqual(
            self.rows(tab="all"),
            [self.old, self.recent, self.playing, self.soon, self.later],
        )

    def test_bad_tab_is_upcoming(self):
        for value in BAD_VALUES + ("ALL", "results "):
            self.assertEqual(
                self.rows(tab=value), [self.playing, self.soon, self.later], value
            )

    def test_tab_links_keep_filters_and_drop_sort(self):
        response = self.get(tab="results", season=self.season.pk, sort="home")
        self.assertContains(response, 'aria-current="page">Results</a>')
        tab_links = response.context["tab_links"]
        for tab, href in tab_links:
            params = query(href)
            self.assertEqual(params["tab"], [tab])
            self.assertEqual(params["season"], [str(self.season.pk)])
            self.assertNotIn("sort", params)
            self.assertNotIn("page", params)


class FilterTests(TableFixtures):
    def setUp(self):
        super().setUp()
        self.gym = Facility.objects.create(name="Coles", source=Facility.Source.NYU)
        self.dunkers = self.make_team("Dunkers", self.hoops, self.season)
        # home + away are Gold; third is Silver.
        self.mine = self.add_match(start=10)
        self.theirs = self.add_match(
            start=20, home_team=self.third, away_team=self.away, facility=self.gym
        )
        self.hoops_match = self.add_match(
            start=30, home_team=self.hoops_team, away_team=self.dunkers
        )
        self.other = self.add_other_season_match()

    def everything(self):
        return [self.other, self.mine, self.theirs, self.hoops_match]

    def test_sport(self):
        self.assertEqual(self.rows(sport=self.hoops.pk), [self.hoops_match])
        self.assertEqual(
            self.rows(sport=self.soccer.pk), [self.other, self.mine, self.theirs]
        )

    def test_season(self):
        self.assertEqual(self.rows(season=self.other_season.pk), [self.other])

    def test_team_home_or_away(self):
        self.assertEqual(self.rows(team=self.away.pk), [self.mine, self.theirs])
        self.assertEqual(self.rows(team=self.third.pk), [self.theirs])

    def test_venue(self):
        self.assertEqual(self.rows(venue=self.gym.pk), [self.theirs])

    def test_mine(self):
        self.assertEqual(self.rows(mine="1"), [self.mine])
        response = self.get(mine="1")
        self.assertContains(response, '<span class="visually-hidden">, on</span>')

    def test_mine_toggle_link(self):
        off = self.get(season=self.season.pk).context["mine_link"]
        self.assertEqual(query(off)["mine"], ["1"])
        self.assertEqual(query(off)["season"], [str(self.season.pk)])
        on = self.get(season=self.season.pk, mine="1").context["mine_link"]
        self.assertNotIn("mine", query(on))
        self.assertEqual(query(on)["season"], [str(self.season.pk)])

    def test_mine_with_no_teams_is_empty(self):
        loner = make_user("loner")
        self.client.force_login(loner)
        self.assertEqual(
            list(self.client.get(URL, {"mine": "1"}).context["matches"]), []
        )

    def test_filters_combine(self):
        self.assertEqual(self.rows(team=self.away.pk, venue=self.gym.pk), [self.theirs])
        self.assertEqual(self.rows(sport=self.hoops.pk, mine="1"), [])

    def test_division_needs_its_season(self):
        self.assertEqual(
            self.rows(season=self.season.pk, division=self.silver.pk), [self.theirs]
        )
        self.assertEqual(
            self.rows(season=self.season.pk, division=self.gold.pk),
            [self.mine, self.theirs],
        )
        # Without the season, or with another season, the division is dropped.
        self.assertEqual(self.rows(division=self.silver.pk), self.everything())
        self.assertEqual(
            self.rows(season=self.other_season.pk, division=self.silver.pk),
            [self.other],
        )

    def test_division_select_only_for_a_season_with_divisions(self):
        self.assertNotContains(self.get(), 'name="division"')
        self.assertNotContains(self.get(season=self.other_season.pk), 'name="division"')
        response = self.get(season=self.season.pk)
        self.assertContains(response, 'name="division"')
        self.assertContains(response, ">Silver</option>")

    def test_bad_values_are_ignored(self):
        foreign = Division.objects.create(season=self.other_season, name="Blue")
        for name in ("sport", "season", "team", "venue", "division", "mine"):
            for value in BAD_VALUES:
                response = self.get(**{name: value})
                self.assertEqual(response.status_code, 200, (name, value))
                self.assertEqual(
                    list(response.context["matches"]),
                    self.everything(),
                    (name, value),
                )
        self.assertEqual(
            self.rows(season=self.season.pk, division=foreign.pk),
            [self.mine, self.theirs, self.hoops_match],
        )

    def test_one_bad_value_keeps_the_other_filters(self):
        self.assertEqual(self.rows(sport="abc", venue=self.gym.pk), [self.theirs])

    def test_selected_values_render(self):
        response = self.get(sport=self.hoops.pk, venue=self.gym.pk)
        self.assertContains(response, f'value="{self.hoops.pk}" selected')
        self.assertContains(response, f'value="{self.gym.pk}" selected')


class SortTests(TableFixtures):
    def setUp(self):
        super().setUp()
        self.aces = self.make_team("Aces", self.hoops, self.season)
        self.zebras = self.make_team("Zebras", self.hoops, self.season)
        self.arena = Facility.objects.create(name="Arena", source=Facility.Source.NYU)
        # first: soccer, Violets v Bobcats, Pier 40.
        self.first = self.add_match(start=10)
        # second: basketball, Zebras v Aces, Arena.
        self.second = self.add_match(
            start=20, home_team=self.zebras, away_team=self.aces, facility=self.arena
        )
        # third: basketball, aces (lowercase sort) v zebras, Pier 40.
        self.last = self.add_match(start=30, home_team=self.aces, away_team=self.zebras)

    def test_every_key_and_direction(self):
        expected = {
            "date": [self.first, self.second, self.last],
            "-date": [self.last, self.second, self.first],
            "sport": [self.second, self.last, self.first],
            "-sport": [self.first, self.second, self.last],
            "home": [self.last, self.first, self.second],
            "-home": [self.second, self.first, self.last],
            "away": [self.second, self.first, self.last],
            "-away": [self.last, self.first, self.second],
            "venue": [self.second, self.first, self.last],
            "-venue": [self.first, self.last, self.second],
        }
        for sort, rows in expected.items():
            for tab in ("upcoming", "all"):
                response = self.get(sort=sort, tab=tab)
                self.assertEqual(list(response.context["matches"]), rows, sort)
                self.assertEqual(response.context["sort"], sort)

    def test_bad_sort_uses_the_tab_default(self):
        for value in BAD_VALUES + ("starts_at", "home_team__name", "--date", "pk"):
            response = self.get(sort=value)
            self.assertEqual(response.context["sort"], "date", value)
            self.assertEqual(
                list(response.context["matches"]),
                [self.first, self.second, self.last],
                value,
            )
            self.assertEqual(
                self.get(sort=value, tab="results").context["sort"], "-date"
            )

    def test_header_links_toggle_and_keep_filters(self):
        response = self.get(sort="home", season=self.season.pk, mine="1", page="2")
        headers = {key: href for key, _, href, _ in response.context["headers"]}
        self.assertEqual(set(headers), {"date", "sport", "home", "away", "venue"})
        for key, href in headers.items():
            params = query(href)
            self.assertEqual(params["season"], [str(self.season.pk)])
            self.assertEqual(params["mine"], ["1"])
            self.assertEqual(params["tab"], ["upcoming"])
            self.assertNotIn("page", params)
            self.assertEqual(params["sort"], ["-home" if key == "home" else key])
        response = self.get(sort="-home")
        headers = {key: href for key, _, href, _ in response.context["headers"]}
        self.assertEqual(query(headers["home"])["sort"], ["home"])
        # Results start newest first, so the date header flips it to oldest first.
        response = self.get(tab="results")
        headers = {key: href for key, _, href, _ in response.context["headers"]}
        self.assertEqual(query(headers["date"])["sort"], ["date"])

    def test_sorted_header_has_aria_sort(self):
        self.assertContains(self.get(sort="-venue"), 'aria-sort="descending"')
        self.assertContains(self.get(sort="away"), 'aria-sort="ascending"')

    def test_filter_form_keeps_tab_and_sort(self):
        response = self.get(tab="all", sort="venue")
        self.assertContains(response, 'type="hidden" name="tab" value="all"')
        self.assertContains(response, 'type="hidden" name="sort" value="venue"')


class PagerTests(TableFixtures):
    def test_fifty_per_page_and_pager_keeps_filters(self):
        self.assertEqual(SCHEDULE_PER_PAGE, 50)
        for hours in range(1, SCHEDULE_PER_PAGE + 2):
            self.add_match(start=hours * 3)
        params = {"season": self.season.pk, "sort": "-date", "mine": "1"}
        response = self.get(**params)
        self.assertEqual(len(response.context["matches"]), SCHEDULE_PER_PAGE)
        next_links = [
            href for href in self.links(response).hrefs if href and "page=2" in href
        ]
        self.assertEqual(len(next_links), 1)
        next_params = query(next_links[0])
        for name, value in params.items():
            self.assertEqual(next_params[name], [str(value)], name)
        self.assertEqual(next_params["tab"], ["upcoming"])
        response = self.client.get(URL + next_links[0].replace("&amp;", "&"))
        self.assertEqual(len(response.context["matches"]), 1)
        self.assertContains(response, "Page 2 of 2")

    def test_bad_page_is_page_one(self):
        self.add_match()
        for value in ("abc", "0", "-1", "9" * 40):
            self.assertEqual(self.get(page=value).status_code, 200)


class RedirectTests(TableFixtures):
    def old_url(self, season=None):
        return reverse("matches:season_schedule", args=[(season or self.season).pk])

    def test_old_season_url_redirects_to_the_filtered_table(self):
        response = self.client.get(self.old_url())
        self.assertRedirects(
            response, f"{URL}?season={self.season.pk}", fetch_redirect_response=False
        )

    def test_division_param_is_kept(self):
        response = self.client.get(self.old_url(), {"division": self.silver.pk})
        self.assertRedirects(
            response,
            f"{URL}?season={self.season.pk}&division={self.silver.pk}",
            fetch_redirect_response=False,
        )
        for value in BAD_VALUES:
            response = self.client.get(self.old_url(), {"division": value})
            self.assertEqual(response.url, f"{URL}?season={self.season.pk}")

    def test_unknown_or_draft_season_is_404(self):
        for pk in (999999, 10**30):
            url = reverse("matches:season_schedule", args=[pk])
            self.assertEqual(self.client.get(url).status_code, 404)
        self.make_draft()
        self.assertEqual(self.client.get(self.old_url()).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.old_url()).status_code, 302)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.old_url())
        self.assertIn(reverse("login"), response.url)


class RowTests(TableFixtures):
    def setUp(self):
        super().setUp()
        self.lee = named_user("lee", "Alex", "Lee")
        self.kim = named_user("kim", "Sam", "Kim")
        Roster.objects.create(team=self.home, player=self.lee)
        Roster.objects.create(team=self.away, player=self.kim)
        # Created first, so it is the soccer scoring stat.
        self.goal = EventType.objects.create(sport=self.soccer, name="Goal")
        self.assist = EventType.objects.create(sport=self.soccer, name="Assist")

    def scored(self, start=-24, **overrides):
        return self.add_match(start=start, home_score=2, away_score=1, **overrides)

    def stat(self, match, player, team, value, event_type=None):
        PlayerStat.objects.create(
            match=match,
            player=player,
            team=team,
            event_type=event_type or self.goal,
            value=value,
        )

    def test_links_and_no_nested_anchors(self):
        match = self.scored()
        response = self.get(tab="results")
        parser = self.links(response)
        self.assertEqual(parser.nested, [])
        detail = reverse("matches:detail", args=[match.pk])
        # The date and the score both open the match page.
        self.assertEqual(parser.hrefs.count(detail), 2)
        for team in (self.home, self.away):
            self.assertIn(reverse("teams:detail", args=[team.pk]), parser.hrefs)
        self.assertContains(response, "2 – 1")

    def test_upcoming_row_links_date_and_vs(self):
        match = self.add_match()
        parser = self.links(self.get())
        self.assertEqual(parser.nested, [])
        detail = reverse("matches:detail", args=[match.pk])
        self.assertEqual(parser.hrefs.count(detail), 2)

    def test_cancelled_badge(self):
        match = self.add_match()
        self.assertNotContains(self.get(), ">Cancelled</span>")
        match.cancel()
        response = self.get()
        self.assertEqual(list(response.context["matches"]), [match])
        self.assertContains(response, ">Cancelled</span>")

    def test_facility_link_only_when_active(self):
        closed = Facility.objects.create(
            name="Old Gym", source=Facility.Source.NYU, is_active=False
        )
        self.add_match(start=10)
        self.add_match(start=20, facility=closed)
        response = self.get()
        self.assertContains(
            response, reverse("facilities:detail", args=[self.field.pk])
        )
        self.assertContains(response, "Old Gym")
        self.assertNotContains(response, reverse("facilities:detail", args=[closed.pk]))

    def test_period_line_with_overtime(self):
        match = self.scored()
        for period, home, away in ((1, 14, 12), (2, 18, 15), (3, 12, 14), (4, 14, 10)):
            MatchPeriodScore.objects.create(
                match=match, period=period, home_points=home, away_points=away
            )
        MatchPeriodScore.objects.create(
            match=match, period=5, home_points=3, away_points=2
        )
        response = self.get(tab="results")
        self.assertEqual(
            response.context["matches"][0].period_line,
            "Q 14-12 18-15 12-14 14-10 OT1 3-2",
        )
        self.assertContains(response, "Q 14-12 18-15 12-14 14-10 OT1 3-2")

    def test_period_line_uses_the_sport_label(self):
        halves = Sport.objects.create(name="Rugby", period_count=2, period_label="Half")
        reds = self.make_team("Reds", halves, self.season)
        blues = self.make_team("Blues", halves, self.season)
        match = self.scored(home_team=reds, away_team=blues)
        MatchPeriodScore.objects.create(
            match=match, period=1, home_points=1, away_points=0
        )
        MatchPeriodScore.objects.create(
            match=match, period=2, home_points=1, away_points=1
        )
        self.assertContains(self.get(tab="results"), "Half 1-0 1-1")

    def test_no_period_line_without_periods(self):
        self.scored()
        row = self.get(tab="results").context["matches"][0]
        self.assertEqual(row.period_line, "")

    def test_top_performer_is_the_best_first_event_type(self):
        match = self.scored()
        self.stat(match, self.lee, self.home, 2)
        self.stat(match, self.kim, self.away, 1)
        # A bigger number in another event type doesn't count.
        self.stat(match, self.kim, self.away, 9, self.assist)
        response = self.get(tab="results")
        top = response.context["matches"][0].top_performer
        self.assertEqual(
            (top.player, top.value, top.event_type), (self.lee, 2, self.goal)
        )
        self.assertContains(response, "Lee</span>")
        self.assertContains(response, '<span class="pn-num fw-medium">2</span>')

    def test_top_performer_tie_goes_by_name(self):
        match = self.scored()
        self.stat(match, self.kim, self.away, 1)
        self.stat(match, self.lee, self.home, 1)
        top = self.get(tab="results").context["matches"][0].top_performer
        self.assertEqual(top.player, self.lee)  # "Alex Lee" sorts before "Sam Kim".

    def test_no_stats_shows_a_dash(self):
        self.scored()
        response = self.get(tab="results")
        self.assertIsNone(response.context["matches"][0].top_performer)
        self.assertContains(response, 'title="No stats">—</span>')

    def test_no_top_performer_for_a_cancelled_match(self):
        match = self.scored()
        self.stat(match, self.lee, self.home, 2)
        match.cancel()
        self.assertIsNone(self.get(tab="results").context["matches"][0].top_performer)

    def test_player_with_no_last_name(self):
        match = self.scored()
        nameless = named_user("nameless", "", "")
        Roster.objects.create(team=self.home, player=nameless)
        self.stat(match, nameless, self.home, 5)
        self.assertContains(self.get(tab="results"), "PlayNYU player</span>")

    def test_query_count_is_the_same_for_3_and_30_matches(self):
        hoops_pts = EventType.objects.create(sport=self.hoops, name="Points")
        dunkers = self.make_team("Dunkers", self.hoops, self.season)
        hooper = named_user("hooper", "Hoop", "Er")
        Roster.objects.create(team=self.hoops_team, player=hooper)

        def add_three(offset):
            soccer = self.scored(start=-offset)
            self.stat(soccer, self.lee, self.home, 2)
            MatchPeriodScore.objects.create(
                match=soccer, period=1, home_points=2, away_points=1
            )
            hoops = self.scored(
                start=-offset - 1, home_team=self.hoops_team, away_team=dunkers
            )
            self.stat(hoops, hooper, self.hoops_team, 20, hoops_pts)
            self.add_match(start=-offset - 2, home_team=self.third)

        add_three(10)
        with CaptureQueriesContext(connection) as three:
            response = self.get(tab="all")
        self.assertEqual(len(response.context["matches"]), 3)
        for offset in range(20, 290, 30):
            add_three(offset)
        with self.assertNumQueries(len(three)):
            response = self.get(tab="all")
        self.assertEqual(len(response.context["matches"]), 30)


class OtherPagesTests(TableFixtures):
    def test_team_page_links_the_season_table(self):
        response = self.client.get(reverse("teams:detail", args=[self.home.pk]))
        self.assertContains(response, f'href="{URL}?season={self.season.pk}"')

    def test_standings_link_the_season_table(self):
        self.add_match(start=-24, home_score=1, away_score=0)
        response = self.client.get(
            reverse("matches:season_standings", args=[self.season.pk])
        )
        self.assertContains(response, f'href="{URL}?season={self.season.pk}"')

    def test_dashboard_links_the_table(self):
        self.assertContains(self.client.get(reverse("core:home")), f'href="{URL}"')

    def test_admins_see_which_seasons_are_drafts(self):
        self.make_draft()
        self.assertContains(self.get(self.admin), ">Fall (draft)</option>")
