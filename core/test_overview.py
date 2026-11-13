import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from chat.models import Message
from chat.moderation import flagged_total
from facilities.models import Facility
from forums.models import Reply, Topic
from matches.models import Match
from matches.tests import make_user
from teams.models import FreeAgentRequest, Season, Sport, Team
from teams.season_rules import SeasonState

from .overview import RECENT_CHANGES_LIMIT, needs_score_matches

HOUR = datetime.timedelta(hours=1)
DAY = datetime.timedelta(days=1)


class OverviewFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.admin = make_user("admin", admin=True)
        cls.player = make_user("player")
        cls.soccer = Sport.objects.create(name="Soccer")
        cls.field = Facility.objects.create(name="Pier 40", source=Facility.Source.NYU)
        cls.seasons = {
            state: Season.objects.create(
                name=f"{state.label} season",
                start_date=datetime.date(2026, 9, 1),
                state=state,
            )
            for state in SeasonState
        }
        cls.url = reverse("core:overview")

    @classmethod
    def make_match(cls, state=SeasonState.ACTIVE, ends_in=-HOUR, **overrides):
        """A two-hour match in a season of the given state, ending now + ends_in."""
        season = cls.seasons[state]
        count = Team.objects.count()
        home, away = (
            Team.objects.create(
                name=f"Team {count + offset}",
                sport=cls.soccer,
                season=season,
                captain=cls.player,
            )
            for offset in (1, 2)
        )
        ends_at = cls.now + ends_in
        values = dict(
            season=season,
            home_team=home,
            away_team=away,
            facility=cls.field,
            starts_at=ends_at - 2 * HOUR,
            ends_at=ends_at,
        )
        values.update(overrides)
        return Match.objects.create(**values)


class NeedsScoreFilterTests(OverviewFixtures):
    def needing(self):
        return list(needs_score_matches(self.now))

    def test_ended_unscored_match_in_live_seasons_is_listed(self):
        active = self.make_match(SeasonState.ACTIVE, ends_in=-2 * HOUR)
        registration = self.make_match(SeasonState.OPEN, ends_in=-HOUR)
        self.assertEqual(self.needing(), [active, registration])

    def test_future_match_is_left_out(self):
        self.make_match(ends_in=3 * HOUR)
        self.assertEqual(self.needing(), [])

    def test_match_in_progress_is_left_out(self):
        self.make_match(ends_in=HOUR)
        self.assertEqual(self.needing(), [])

    def test_cancelled_match_is_left_out(self):
        self.make_match(status=Match.Status.CANCELLED)
        self.assertEqual(self.needing(), [])

    def test_scored_match_is_left_out(self):
        self.make_match(home_score=2, away_score=0)
        self.assertEqual(self.needing(), [])

    def test_draft_and_closed_seasons_are_left_out(self):
        self.make_match(SeasonState.DRAFT)
        self.make_match(SeasonState.CLOSED)
        self.assertEqual(self.needing(), [])

    def test_every_listed_match_can_be_scored(self):
        for state in SeasonState:
            self.make_match(state)
        self.make_match(status=Match.Status.CANCELLED)
        listed = Match.objects.needing_score(self.now).select_related("season")
        self.assertEqual(
            {match.pk for match in listed},
            {
                match.pk
                for match in Match.objects.select_related("season")
                if match.can_change
            },
        )


class OverviewAccessTests(OverviewFixtures):
    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_non_admin_gets_403(self):
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_scorekeeper_gets_403(self):
        self.client.force_login(make_user("keeper", scorekeeper=True))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_admin_sees_the_page(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/overview.html")

    def test_superuser_sees_the_page(self):
        root = make_user("root")
        root.is_superuser = True
        root.save()
        self.client.force_login(root)
        self.assertEqual(self.client.get(self.url).status_code, 200)


class OverviewNavTests(OverviewFixtures):
    def nav_link(self):
        return f'href="{self.url}"'

    def test_admin_sees_the_nav_link(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, self.nav_link())

    def test_player_does_not_see_the_nav_link(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, self.nav_link())

    def test_overview_is_highlighted_and_home_is_not(self):
        self.client.force_login(self.admin)
        html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn(f'href="{self.url}" aria-current="page"', html)
        self.assertNotIn(f'href="{reverse("core:home")}" aria-current="page"', html)

    def test_home_is_still_highlighted_on_the_dashboard(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn(f'href="{reverse("core:home")}" aria-current="page"', html)
        self.assertNotIn(f'href="{self.url}" aria-current="page"', html)


class OverviewContentTests(OverviewFixtures):
    def setUp(self):
        self.client.force_login(self.admin)

    def get(self):
        return self.client.get(self.url)

    def test_counts_and_lists(self):
        unscored = self.make_match(SeasonState.ACTIVE, ends_in=-HOUR)
        self.make_match(SeasonState.ACTIVE, ends_in=-DAY, home_score=1, away_score=1)
        self.make_match(SeasonState.CLOSED, ends_in=-DAY)
        upcoming = self.make_match(SeasonState.OPEN, ends_in=DAY)
        self.make_match(SeasonState.OPEN, ends_in=DAY, status=Match.Status.CANCELLED)
        self.make_match(SeasonState.DRAFT, ends_in=DAY)
        FreeAgentRequest.objects.create(
            player=self.player, season=self.seasons[SeasonState.OPEN], sport=self.soccer
        )
        FreeAgentRequest.objects.create(
            player=self.player,
            season=self.seasons[SeasonState.CLOSED],
            sport=self.soccer,
        )
        Facility.objects.create(
            name="Closed gym", source=Facility.Source.NYU, is_active=False
        )

        response = self.get()

        counts = response.context["counts"]
        self.assertEqual(counts["pending_requests"], 1)
        self.assertEqual(counts["needs_score"], 1)
        self.assertEqual(counts["flagged"], 0)
        self.assertEqual(counts["upcoming_matches"], 1)
        self.assertEqual(counts["teams"], 12)
        self.assertEqual(counts["active_facilities"], 1)
        self.assertEqual(
            [row["match"] for row in response.context["needs_score_rows"]], [unscored]
        )
        self.assertEqual(list(response.context["upcoming_matches"]), [upcoming])
        self.assertContains(response, "12 teams")
        self.assertContains(response, "1 active")

    def test_needs_score_row_links_to_the_score_view(self):
        match = self.make_match()
        response = self.get()
        self.assertContains(
            response, f'href="{reverse("matches:score", args=[match.pk])}"'
        )
        self.assertContains(response, "Record score")
        self.assertEqual(
            self.client.get(reverse("matches:score", args=[match.pk])).status_code, 200
        )

    def test_empty_lists_show_empty_states(self):
        Season.objects.all().delete()
        AuditLog.objects.all().delete()
        response = self.get()
        self.assertContains(response, "Every finished match has a score")
        self.assertContains(response, "No upcoming matches")
        self.assertContains(response, "No current seasons")
        self.assertContains(response, "No changes yet")
        self.assertNotContains(response, "Record score")

    def test_long_needs_score_list_is_capped_with_the_full_count(self):
        for _ in range(11):
            self.make_match()
        response = self.get()
        self.assertEqual(response.context["counts"]["needs_score"], 11)
        self.assertEqual(len(response.context["needs_score_rows"]), 10)
        self.assertContains(response, "See every match")

    def test_stat_cards_and_quick_links_point_at_their_pages(self):
        response = self.get()
        for name in (
            "teams:manage_free_agents",
            "chat:moderation_queue",
            "matches:manage",
            "matches:standings",
            "facilities:manage",
        ):
            self.assertContains(response, f'href="{reverse(name)}"')
        self.assertContains(response, 'href="#needs-a-score"')
        self.assertContains(response, 'id="needs-a-score"')
        self.assertContains(response, "card-link-pop", count=4)

    def make_flagged_content(self, messages=0, topics=0, replies=0):
        """The given number of flagged rows of each kind, plus one clean row each."""
        team = Team.objects.create(
            name="Violets", sport=self.soccer, captain=self.player
        )
        home = Topic.objects.create(author=self.player, title="Clean", body="Fine")
        for number in range(messages + 1):
            Message.objects.create(
                team=team, author=self.player, body="Hi", is_flagged=number < messages
            )
        for number in range(topics):
            Topic.objects.create(
                author=self.player, title=f"Bad {number}", body="Bad", is_flagged=True
            )
        for number in range(replies + 1):
            Reply.objects.create(
                topic=home, author=self.player, body="Hi", is_flagged=number < replies
            )

    def queue_row_count(self):
        context = self.client.get(reverse("chat:moderation_queue")).context
        return sum(
            len(context[name])
            for name in ("flagged", "flagged_topics", "flagged_replies")
        )

    def test_flagged_count_matches_the_moderation_queue(self):
        self.make_flagged_content(messages=2, topics=3, replies=4)
        response = self.get()
        self.assertEqual(response.context["counts"]["flagged"], 9)
        self.assertEqual(response.context["counts"]["flagged"], self.queue_row_count())
        self.assertContains(
            response, "Messages, topics and replies in the moderation queue"
        )

    def test_flagged_count_includes_forum_topics_and_replies(self):
        self.make_flagged_content(topics=1, replies=2)
        self.assertEqual(self.get().context["counts"]["flagged"], 3)
        self.assertEqual(self.queue_row_count(), 3)

    def test_unflagged_content_is_not_counted(self):
        self.make_flagged_content()
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(Topic.objects.count(), 1)
        self.assertEqual(Reply.objects.count(), 1)
        self.assertEqual(self.get().context["counts"]["flagged"], 0)
        self.assertEqual(self.queue_row_count(), 0)

    def test_flagged_count_takes_one_query_per_kind(self):
        self.make_flagged_content(messages=2, topics=2, replies=2)
        with self.assertNumQueries(3):
            self.assertEqual(flagged_total(), 6)

    def test_seasons_list_leaves_out_closed_seasons(self):
        # "Recent changes" would also name the closed season.
        AuditLog.objects.all().delete()
        response = self.get()
        self.assertEqual(
            {season.state for season in response.context["seasons"]},
            {SeasonState.DRAFT, SeasonState.OPEN, SeasonState.ACTIVE},
        )
        self.assertNotContains(response, "Closed season")

    def test_season_state_counts_cover_every_state(self):
        Season.objects.create(
            name="Old", start_date=datetime.date(2025, 9, 1), state=SeasonState.CLOSED
        )
        self.assertEqual(
            self.get().context["season_counts"],
            [
                {"label": "Draft", "count": 1},
                {"label": "Open", "count": 1},
                {"label": "Active", "count": 1},
                {"label": "Closed", "count": 2},
            ],
        )

    def test_recent_changes_show_the_latest_rows_with_actor(self):
        AuditLog.objects.all().delete()
        for number in range(RECENT_CHANGES_LIMIT + 2):
            AuditLog.objects.create(
                actor=self.admin if number % 2 else None,
                action=AuditLog.Action.UPDATED,
                object_type="Season",
                object_id=str(number),
                object_repr=f"Change {number}",
            )
        response = self.get()
        changes = list(response.context["recent_changes"])
        self.assertEqual(len(changes), RECENT_CHANGES_LIMIT)
        self.assertEqual(changes[0].object_repr, "Change 9")
        self.assertContains(response, "Updated season")
        self.assertContains(response, "Change 9")
        self.assertNotContains(response, "Change 1<")
        self.assertContains(response, "System")
        self.assertContains(response, self.admin.email)

    def test_query_count_does_not_grow_with_rows(self):
        def query_count():
            with CaptureQueriesContext(connection) as queries:
                self.get()
            return len(queries)

        self.make_match(ends_in=-HOUR)
        self.make_match(ends_in=DAY)
        baseline = query_count()
        for _ in range(3):
            self.make_match(ends_in=-HOUR)
            self.make_match(ends_in=DAY)
        self.assertEqual(query_count(), baseline)
