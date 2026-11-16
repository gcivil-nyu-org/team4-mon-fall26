import datetime
from html.parser import HTMLParser

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from teams.models import EventType, Roster
from teams.season_rules import SeasonState

from .match_context import season_results, season_teams
from .models import Match, MatchAppearance, MatchPeriodScore, PlayerStat
from .test_match_sheet import SheetFixtures, named_user
from .tests import make_user

HOUR = datetime.timedelta(hours=1)


class MatchDetailTests(SheetFixtures):
    def url(self, match=None):
        return reverse("matches:detail", args=[(match or self.match).pk])

    def get(self, user=None, match=None):
        self.client.force_login(user or self.player)
        return self.client.get(self.url(match))

    def score(self, periods=(), stats=None, played=()):
        self.save(
            periods=list(periods),
            final=(2, 1),
            stats=stats or {},
            played=set(played),
        )

    def started(self, **overrides):
        now = timezone.now()
        return self.assign(starts_at=now - HOUR, ends_at=now + HOUR, **overrides)

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_player_sees_page(self):
        Roster.objects.create(team=self.home, player=self.player)
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Violets vs Bobcats")
        # Team pages are public, so both team names link.
        self.assertContains(response, reverse("teams:detail", args=[self.home.pk]))
        self.assertContains(response, reverse("teams:detail", args=[self.away.pk]))
        facility_url = reverse("facilities:detail", args=[self.field.pk])
        self.assertContains(response, facility_url)
        self.field.is_active = False
        self.field.save()
        self.assertNotContains(self.get(), facility_url)
        self.assertEqual(response.context["nav_section"], "schedule")

    def test_draft_season_hidden(self):
        self.season.state = SeasonState.DRAFT
        self.season.save()
        self.assertEqual(self.get().status_code, 404)
        self.assertEqual(self.get(self.admin).status_code, 200)

    def test_period_table(self):
        self.score(periods=[(1, 1, 0), (2, 0, 0), (3, 0, 1), (4, 1, 0), (5, 3, 2)])
        response = self.get()
        for label in ("Q1", "Q2", "Q3", "Q4", "OT1"):
            self.assertContains(response, f'<th class="text-end">{label}</th>')
        self.assertContains(response, 'title="Total">T</th>')
        self.assertNotContains(response, "OT2")
        self.assertContains(response, "5 – 3")

    def test_no_period_table_without_periods(self):
        self.score()
        response = self.get()
        self.assertNotContains(response, ">Q1<")
        self.assertNotContains(response, "Periods")

    def test_did_not_play(self):
        self.score(played=[self.pair(self.home, self.alex)])
        response = self.get()
        self.assertContains(response, "Did not play", count=2)  # Sam and Jo.
        self.assertContains(response, "Final")

    def test_stats_show(self):
        self.score(stats={self.key(self.home, self.alex): 3})
        response = self.get()
        self.assertContains(response, 'title="Goal"')
        self.assertContains(response, '<td class="text-end pn-num">3</td>')

    def test_left_team_row(self):
        leaver = named_user("bea", "Bea", "Zed")
        Roster.objects.create(team=self.home, player=leaver)
        self.score(stats={self.key(self.home, leaver): 4})
        Roster.objects.filter(player=leaver).delete()
        response = self.get()
        self.assertContains(response, "Bea Zed")
        self.assertContains(response, "Left team")
        self.assertContains(response, '<td class="text-end pn-num">4</td>')

    def test_no_email(self):
        nameless = make_user("nameless")
        Roster.objects.create(team=self.away, player=nameless)
        response = self.get()
        self.assertContains(response, "PlayNYU player")
        self.assertNotContains(response, nameless.email)

    def test_new_event_type_shows_zero(self):
        self.score(stats={self.key(self.home, self.alex): 1})
        EventType.objects.create(sport=self.soccer, name="Save")
        response = self.get()
        self.assertContains(response, 'title="Save"')
        self.assertContains(
            response, '<td class="text-end pn-num text-secondary">0</td>'
        )

    def test_no_stat_columns_without_event_types(self):
        EventType.objects.filter(sport=self.soccer).delete()
        self.score()
        response = self.get()
        self.assertNotContains(response, 'title="Goal"')
        self.assertContains(response, "Alex Lee")

    def test_before_result(self):
        later = self.assign(
            starts_at=timezone.now() + HOUR, ends_at=timezone.now() + 2 * HOUR
        )
        response = self.get(match=later)
        self.assertContains(response, "Stats appear after the score is in.")
        self.assertNotContains(response, 'title="Goal"')
        self.assertNotContains(response, "Did not play")
        self.assertContains(response, "Scheduled")

    def test_awaiting_score(self):
        match = self.started()
        match.ends_at = timezone.now() - datetime.timedelta(minutes=1)
        match.starts_at = match.ends_at - HOUR
        match.save()
        self.assertContains(self.get(match=match), "Awaiting score")

    def test_cancelled(self):
        self.score(periods=[(1, 1, 0), (2, 0, 0), (3, 0, 1), (4, 1, 0)])
        PlayerStat.objects.all().delete()
        MatchPeriodScore.objects.all().delete()
        MatchAppearance.objects.all().delete()
        self.match.home_score = self.match.away_score = None
        self.match.save()
        self.match.cancel()
        response = self.get()
        self.assertContains(response, "Cancelled")
        self.assertNotContains(response, 'title="Goal"')
        self.assertNotContains(response, "Stats appear after")
        self.assertContains(response, "Alex Lee")
        self.assertIsNone(response.context["score_url"])

    def test_empty_roster(self):
        Roster.objects.filter(team=self.away).delete()
        self.assertContains(self.get(), "No players on this roster.")

    def test_viewer_row_marked(self):
        Roster.objects.create(team=self.home, player=self.player)
        self.assertContains(self.get(), "pn-row-me")

    def test_button_admin(self):
        response = self.get(self.admin)
        url = reverse("matches:score", args=[self.match.pk])
        self.assertEqual(response.context["score_url"], url)
        self.assertContains(response, url)
        self.assertIsNone(self.get().context["score_url"])

    def test_button_keeper(self):
        match = self.started()
        self.assertEqual(
            self.get(self.keeper, match).context["score_url"],
            reverse("matches:submit_score", args=[match.pk]),
        )
        self.assertIsNone(self.get(self.other_keeper, match).context["score_url"])
        later = self.assign(
            starts_at=timezone.now() + HOUR, ends_at=timezone.now() + 2 * HOUR
        )
        self.assertIsNone(self.get(self.keeper, later).context["score_url"])

    def test_button_hidden_after_role_loss(self):
        match = self.started()
        self.remove_role(self.keeper)
        self.assertIsNone(self.get(self.keeper, match).context["score_url"])

    def test_button_hidden_closed_season(self):
        self.season.state = SeasonState.CLOSED
        self.season.save()
        self.assertIsNone(self.get(self.admin).context["score_url"])

    def scored_match(self, size):
        """A scored match with `size` players, periods, stats and one leaver."""
        home = self.make_team(f"Home {size}", self.soccer, self.season)
        away = self.make_team(f"Away {size}", self.soccer, self.season)
        match = self.build(home_team=home, away_team=away, home_score=4, away_score=0)
        match.save()
        for period in range(1, 5):
            MatchPeriodScore.objects.create(
                match=match, period=period, home_points=1, away_points=0
            )
        players = [named_user(f"p{size}-{i}", "P", str(i)) for i in range(size + 1)]
        for index, player in enumerate(players):
            team = (home, away)[index % 2]
            Roster.objects.create(team=team, player=player)
            MatchAppearance.objects.create(match=match, team=team, player=player)
            for event_type in (self.goal, self.assist):
                PlayerStat.objects.create(
                    match=match,
                    team=team,
                    player=player,
                    event_type=event_type,
                    value=1,
                )
        # The last player left the team after the match.
        Roster.objects.filter(player=players[-1]).delete()
        # players[0] views the page as a home team member.
        return match, players[0]

    def test_query_count_fixed(self):
        small, small_viewer = self.scored_match(2)
        large, large_viewer = self.scored_match(20)
        self.client.force_login(small_viewer)
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(self.url(small)).status_code, 200)
        expected = len(captured)
        self.assertLessEqual(expected, 20)
        self.client.force_login(large_viewer)
        with self.assertNumQueries(expected):
            response = self.client.get(self.url(large))
        self.assertContains(response, "Left team")
        self.assertEqual(len(response.context["tables"][0][1]), 11)


class LinkCollector(HTMLParser):
    """Collects hrefs and records any <a> opened inside another <a>."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.nested = []
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if self.depth:
            self.nested.append(href)
        self.depth += 1
        self.hrefs.append(href)

    def handle_endtag(self, tag):
        if tag == "a" and self.depth:
            self.depth -= 1


class MatchRowLinkTests(SheetFixtures):
    def href(self):
        return f'href="{reverse("matches:detail", args=[self.match.pk])}"'

    def assert_row_links(self, response):
        """The page links the match and both teams, with no nested links."""
        parser = LinkCollector()
        parser.feed(response.content.decode())
        self.assertEqual(parser.nested, [])
        self.assertIn(reverse("matches:detail", args=[self.match.pk]), parser.hrefs)
        for team in (self.home, self.away):
            self.assertIn(reverse("teams:detail", args=[team.pk]), parser.hrefs)

    def test_season_schedule_row_has_no_nested_links(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse("matches:schedule"), {"tab": "all"})
        self.assert_row_links(response)

    def test_my_matches_row_has_no_nested_links(self):
        self.match.scorekeeper = self.keeper
        self.match.save()
        self.client.force_login(self.keeper)
        self.assert_row_links(self.client.get(reverse("matches:mine")))

    def test_season_schedule_links_match(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse("matches:schedule"), {"tab": "all"})
        self.assertContains(response, self.href())

    def test_team_page_links_match(self):
        Roster.objects.create(team=self.home, player=self.player)
        self.client.force_login(self.player)
        response = self.client.get(reverse("teams:detail", args=[self.home.pk]))
        self.assertContains(response, self.href())

    def test_my_matches_links_match(self):
        self.match.scorekeeper = self.keeper
        self.match.save()
        self.client.force_login(self.keeper)
        self.assertContains(self.client.get(reverse("matches:mine")), self.href())

    def test_my_matches_draft_season_not_linked(self):
        # The match page is 404 for a scorekeeper while the season is a draft.
        self.match.scorekeeper = self.keeper
        self.match.save()
        self.season.state = SeasonState.DRAFT
        self.season.save()
        self.client.force_login(self.keeper)
        response = self.client.get(reverse("matches:mine"))
        self.assertContains(response, "Violets")
        self.assertNotContains(response, self.href())
        detail = reverse("matches:detail", args=[self.match.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)

    def draft_my_matches(self, keeper):
        self.match.scorekeeper = keeper
        self.match.save()
        self.season.state = SeasonState.DRAFT
        self.season.save()
        self.client.force_login(keeper)
        return self.client.get(reverse("matches:mine"))

    def test_my_matches_draft_season_teams_not_linked(self):
        # teams:detail is 404 for a scorekeeper while the season is a draft.
        response = self.draft_my_matches(self.keeper)
        for team in (self.home, self.away):
            self.assertContains(response, team.name)
            team_url = reverse("teams:detail", args=[team.pk])
            self.assertNotContains(response, f'href="{team_url}"')
            self.assertEqual(self.client.get(team_url).status_code, 404)

    def test_my_matches_draft_season_teams_linked_for_league_admin(self):
        assign_role(self.keeper, LEAGUE_ADMIN_ROLE)
        response = self.draft_my_matches(self.keeper)
        for team in (self.home, self.away):
            team_url = reverse("teams:detail", args=[team.pk])
            self.assertContains(response, f'href="{team_url}"')
            self.assertEqual(self.client.get(team_url).status_code, 200)


class SeasonQueryTests(SheetFixtures):
    def day(self, offset, **overrides):
        start = self.match.starts_at + datetime.timedelta(days=offset)
        values = dict(starts_at=start, ends_at=start + HOUR)
        values.update(overrides)
        match = self.build(**values)
        match.save()
        return match

    def test_season_results_skip_cancelled_unscored_and_other_seasons(self):
        scored = self.day(1, home_score=2, away_score=1)
        cancelled = self.day(2, home_score=1, away_score=1)
        Match.objects.filter(pk=cancelled.pk).update(status=Match.Status.CANCELLED)
        self.day(3)  # No score.
        other_home = self.make_team("Other home", self.soccer, self.other_season)
        other_away = self.make_team("Other away", self.soccer, self.other_season)
        self.day(
            4,
            season=self.other_season,
            home_team=other_home,
            away_team=other_away,
            home_score=1,
            away_score=0,
        )
        with self.assertNumQueries(1):
            got = season_results(self.match)
        self.assertEqual([r.pk for r in got], [scored.pk])
        self.assertEqual(
            (got[0].home_id, got[0].away_id, got[0].home_score, got[0].away_score),
            (self.home.pk, self.away.pk, 2, 1),
        )

    def test_season_results_ordered_by_start_then_pk(self):
        late = self.day(2, home_score=1, away_score=0)
        first = self.day(1, home_score=1, away_score=0)
        second = self.day(1, home_score=0, away_score=0)
        got = [r.pk for r in season_results(self.match)]
        self.assertEqual(got, [first.pk, second.pk, late.pk])

    def test_season_teams_one_query_by_name(self):
        with self.assertNumQueries(1):
            teams = season_teams(self.match)
            [t.division for t in teams]
        self.assertEqual([t.name for t in teams], sorted(t.name for t in teams))
        self.assertIn(self.home, teams)
