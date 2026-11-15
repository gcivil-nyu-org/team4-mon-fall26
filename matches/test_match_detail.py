import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from teams.models import EventType, Roster
from teams.season_rules import SeasonState

from .models import MatchAppearance, MatchPeriodScore, PlayerStat
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
        # Team pages are for members, so only the viewer's team links.
        self.assertContains(response, reverse("teams:detail", args=[self.home.pk]))
        self.assertNotContains(response, reverse("teams:detail", args=[self.away.pk]))
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

    def test_query_count_fixed(self):
        self.score(stats={self.key(self.home, self.alex): 1})
        self.client.force_login(self.player)
        small = self.count_queries()
        for name in ("p1", "p2"):
            user = make_user(name)
            Roster.objects.create(team=self.away, player=user)
            PlayerStat.objects.create(
                match=self.match,
                team=self.away,
                player=user,
                event_type=self.goal,
                value=1,
            )
            MatchAppearance.objects.create(
                match=self.match, team=self.away, player=user
            )
        self.assertEqual(self.count_queries(), small)

    def count_queries(self):
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(self.url()).status_code, 200)
        return len(captured)


class MatchRowLinkTests(SheetFixtures):
    def href(self):
        return f'href="{reverse("matches:detail", args=[self.match.pk])}"'

    def test_season_schedule_links_match(self):
        self.client.force_login(self.player)
        response = self.client.get(
            reverse("matches:season_schedule", args=[self.season.pk])
        )
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
