"""Every match row opens its match page with one stretched link."""

from django.urls import reverse

from teams.models import Season
from teams.season_rules import SeasonState

from .models import Match, MatchAppearance
from .test_match_detail import LinkCollector
from .test_schedule import ScheduleFixtures
from .tests import make_user


class RowLinkCollector(LinkCollector):
    """LinkCollector that also records the hrefs of stretched links."""

    def __init__(self):
        super().__init__()
        self.stretched = []
        self.labels = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attrs = dict(attrs)
        if tag == "a" and "stretched-link" in (attrs.get("class") or "").split():
            self.stretched.append(attrs.get("href"))
            self.labels.append(attrs.get("aria-label"))


class RowLinkTests(ScheduleFixtures):
    def collect(self, response):
        self.assertEqual(response.status_code, 200)
        parser = RowLinkCollector()
        parser.feed(response.content.decode())
        self.assertEqual(parser.nested, [])
        return parser

    def detail(self, match):
        return reverse("matches:detail", args=[match.pk])

    def assert_rows(self, parser, matches):
        """Exactly one stretched link per match, and the team links stay."""
        self.assertCountEqual(parser.stretched, [self.detail(m) for m in matches])
        for match in matches:
            for team in (match.home_team, match.away_team):
                self.assertIn(reverse("teams:detail", args=[team.pk]), parser.hrefs)

    def test_schedule_table(self):
        scored = self.add_match(start=-24, home_score=2, away_score=1)
        upcoming = self.add_match(start=24)
        cancelled = self.add_match(start=48)
        cancelled.cancel()
        response = self.client.get(reverse("matches:schedule"), {"tab": "all"})
        parser = self.collect(response)
        self.assert_rows(parser, [scored, upcoming, cancelled])
        for label in parser.labels:
            self.assertTrue(label.startswith("Open match: Violets vs Bobcats, "))
        self.assertContains(response, 'class="pn-row-link')
        # The date stays a separate link to the match page.
        self.assertEqual(parser.hrefs.count(self.detail(upcoming)), 2)

    def test_team_page(self):
        matches = [self.add_match(start=24), self.add_match(start=-24)]
        response = self.client.get(reverse("teams:detail", args=[self.home.pk]))
        self.assert_rows(self.collect(response), matches)

    def test_dashboard(self):
        match = self.add_match(start=24)
        self.assert_rows(self.collect(self.client.get(reverse("core:home"))), [match])

    def test_facility_page(self):
        match = self.add_match(start=24)
        response = self.client.get(reverse("facilities:detail", args=[self.field.pk]))
        self.assert_rows(self.collect(response), [match])

    def test_profile_page(self):
        match = self.add_match(start=-24, home_score=1, away_score=0)
        MatchAppearance.objects.create(match=match, player=self.player, team=self.home)
        response = self.client.get(reverse("profiles:detail", args=[self.player.pk]))
        self.assert_rows(self.collect(response), [match])

    def test_overview_rows_keep_the_action_button(self):
        needs_score = self.add_match(start=-5)
        upcoming = self.add_match(start=24)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("core:overview"))
        parser = self.collect(response)
        self.assert_rows(parser, [needs_score, upcoming])
        self.assertIn(reverse("matches:score", args=[needs_score.pk]), parser.hrefs)

    def test_my_matches_draft_rows_get_no_stretched_link(self):
        keeper = make_user("keeper", scorekeeper=True)
        live = self.add_match(start=24, scorekeeper=keeper)
        draft = self.add_other_season_match()
        Match.objects.filter(pk=draft.pk).update(scorekeeper=keeper)
        Season.objects.filter(pk=self.other_season.pk).update(state=SeasonState.DRAFT)
        self.client.force_login(keeper)
        parser = self.collect(self.client.get(reverse("matches:mine")))
        self.assertEqual(parser.stretched, [self.detail(live)])
        self.assertNotIn(self.detail(draft), parser.hrefs)
