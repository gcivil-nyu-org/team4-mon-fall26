import datetime
import zoneinfo

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as date_format

from matches.models import Match
from matches.test_schedule import ScheduleFixtures

from .models import Facility


class FacilitySchedulePageTests(ScheduleFixtures):
    def url(self):
        return reverse("facilities:detail", args=[self.field.pk])

    def get(self, **params):
        return self.client.get(self.url(), params)

    def test_upcoming_match_listed_under_its_day(self):
        ny = zoneinfo.ZoneInfo("America/New_York")
        day = timezone.localdate() + datetime.timedelta(days=3)
        start = datetime.datetime.combine(day, datetime.time(18), tzinfo=ny)
        self.build(starts_at=start, ends_at=start + datetime.timedelta(hours=2)).save()
        response = self.get()
        self.assertContains(response, "Violets")
        self.assertContains(response, "Bobcats")
        self.assertContains(response, date_format(day, "l, M j"))

    def test_rows_show_the_sport_not_a_link_to_this_page(self):
        self.add_match()
        response = self.get()
        self.assertNotContains(response, f'href="{self.url()}"')

    def test_cancelled_shows_badge(self):
        self.add_match(status=Match.Status.CANCELLED)
        response = self.get()
        self.assertContains(response, "Cancelled")
        self.assertEqual(response.context["upcoming_count"], 0)

    def test_recent_results_show_score(self):
        self.add_match(start=-30, home_score=2, away_score=1)
        self.assertContains(self.get(), "2 – 1")

    def test_stats(self):
        first = self.add_match(start=5)
        self.add_match(start=30)
        self.add_match(start=60)
        response = self.get()
        self.assertEqual(response.context["upcoming_count"], 3)
        self.assertEqual(response.context["next_game"], first)
        when = date_format(timezone.localtime(first.starts_at), "D M j, g:i A")
        self.assertContains(response, f'<div class="h3 mb-0 pn-num">{when}</div>')

    def test_no_games_empty_states(self):
        response = self.get()
        self.assertContains(response, "None scheduled")
        self.assertContains(response, "No upcoming games here")
        self.assertContains(response, "No results yet")
        self.assertNotContains(response, "Games by sport")

    def test_pager_shows_with_more_than_twenty(self):
        for i in range(21):
            self.add_match(start=i + 1)
        response = self.get()
        self.assertContains(response, 'aria-label="Upcoming game pages"')
        self.assertContains(response, "?page=2")
        self.assertEqual(len(self.get(page=2).context["page_obj"]), 1)

    def test_no_pager_with_one_page(self):
        self.add_match()
        self.assertNotContains(self.get(), "Upcoming game pages")

    def test_sport_counts_render(self):
        self.add_match(start=1)
        self.add_match(start=-30)
        response = self.get()
        self.assertContains(response, "Games by sport")
        self.assertContains(response, '<span class="pn-num">2</span>', html=True)

    def test_query_count_is_constant(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.get()
            return len(queries)

        self.add_match(start=5)
        self.add_match(start=-30, home_score=1, away_score=0)
        few = count()
        for i in range(15):
            self.add_match(start=i + 10)
            self.add_match(start=-(i + 40), home_score=1, away_score=0)
        self.assertEqual(count(), few)

    def test_inactive_facility_still_404(self):
        Facility.objects.filter(pk=self.field.pk).update(is_active=False)
        self.assertEqual(self.get().status_code, 404)

    def test_draft_season_hidden_from_player(self):
        self.add_match()
        self.make_draft()
        self.assertContains(self.get(), "No upcoming games here")
