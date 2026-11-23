import datetime

from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from teams.models import Season
from teams.season_rules import SeasonState

from .models import Match
from .scorekeeping import group_assigned_matches
from .sheet_forms import MatchSheet
from .tests import ScorekeeperFixtures

HOUR = datetime.timedelta(hours=1)
DAY = datetime.timedelta(days=1)
SCORE = {"home_score": "2", "away_score": "1"}


class RelativeMatches(ScorekeeperFixtures):
    """Matches placed relative to now, so the tests don't depend on the date."""

    def played(self, days_ago=1, **overrides):
        start = timezone.now() - days_ago * DAY
        return self.assign(starts_at=start, ends_at=start + HOUR, **overrides)

    def under_way(self, **overrides):
        now = timezone.now()
        return self.assign(starts_at=now - HOUR, ends_at=now + HOUR, **overrides)

    def later(self, days_ahead=1, **overrides):
        start = timezone.now() + days_ahead * DAY
        return self.assign(starts_at=start, ends_at=start + HOUR, **overrides)

    def submit_url(self, match):
        return reverse("matches:submit_score", args=[match.pk])


class MatchScoreTimingTests(RelativeMatches):
    def test_match_can_be_scored_once_it_starts(self):
        self.assertFalse(self.later().can_submit_score)
        self.assertTrue(self.under_way().can_submit_score)
        self.assertTrue(self.played().can_submit_score)

    def test_started_match_still_needs_a_live_season_and_no_cancel(self):
        cancelled = self.played()
        cancelled.cancel()
        self.assertFalse(cancelled.can_submit_score)
        closed = self.played(days_ago=2)
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        closed.refresh_from_db()
        self.assertFalse(closed.can_submit_score)


class GroupAssignedMatchesTests(RelativeMatches):
    def test_groups_by_what_each_match_needs(self):
        older = self.played(days_ago=3)
        newer = self.played(days_ago=1)
        live = self.under_way()
        soon = self.later(days_ahead=1)
        far = self.later(days_ahead=5)
        old_result = self.played(days_ago=6, home_score=1, away_score=0)
        new_result = self.played(days_ago=2, home_score=3, away_score=3)
        groups = group_assigned_matches(self.keeper)
        self.assertEqual(groups["needs_score"], [older, newer, live])
        self.assertEqual(groups["upcoming"], [soon, far])
        self.assertEqual(groups["scored"], [new_result, old_result])
        self.assertEqual(groups["unscored"], [])

    def test_only_the_users_own_matches(self):
        self.played(keeper=self.other_keeper)
        self.build().save()
        groups = group_assigned_matches(self.keeper)
        self.assertEqual(sum(groups.values(), []), [])

    def test_cancelled_matches_never_need_a_score(self):
        past = self.played()
        past.cancel()
        future = self.later()
        future.cancel()
        groups = group_assigned_matches(self.keeper)
        self.assertEqual(groups["needs_score"], [])
        self.assertEqual(groups["upcoming"], [future])
        self.assertEqual(groups["unscored"], [past])

    def test_closed_season_matches_do_not_need_a_score(self):
        past = self.played()
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        groups = group_assigned_matches(self.keeper)
        self.assertEqual(groups["needs_score"], [])
        self.assertEqual(groups["unscored"], [past])


class MyMatchesSectionTests(RelativeMatches):
    def setUp(self):
        self.client.force_login(self.keeper)
        self.url = reverse("matches:mine")

    def test_sections_in_order_with_empty_states(self):
        html = self.client.get(self.url).content.decode()
        titles = [">Needs a score<", ">Upcoming<", ">Scored<"]
        positions = [html.index(title) for title in titles]
        self.assertEqual(positions, sorted(positions))
        for text in ("All scores are in", "No upcoming matches", "No scores yet"):
            self.assertIn(text, html)
        self.assertNotIn("Not scored", html)

    def test_no_score_button_before_the_match_starts(self):
        upcoming = self.later()
        response = self.client.get(self.url)
        self.assertEqual(response.context["groups"]["upcoming"], [upcoming])
        self.assertNotContains(response, self.submit_url(upcoming))

    def test_started_match_has_the_score_button(self):
        match = self.under_way()
        response = self.client.get(self.url)
        self.assertContains(response, self.submit_url(match))
        self.assertContains(response, "Submit score")

    def test_only_one_primary_button(self):
        for days_ago in (1, 2, 3):
            self.played(days_ago=days_ago)
        response = self.client.get(self.url)
        self.assertContains(response, "Submit score", count=3)
        self.assertContains(response, "btn-primary", count=1)

    def test_scored_match_has_no_score_button(self):
        scored = self.played(home_score=2, away_score=1)
        response = self.client.get(self.url)
        self.assertNotContains(response, self.submit_url(scored))
        self.assertNotContains(response, "btn-primary")

    def test_each_row_shows_both_team_logos(self):
        self.played()
        self.later()
        self.assertContains(self.client.get(self.url), "pn-logo", count=4)

    def test_past_cancelled_match_is_listed_without_a_button(self):
        match = self.played()
        match.cancel()
        response = self.client.get(self.url)
        self.assertContains(response, "Not scored")
        self.assertContains(response, "Cancelled")
        self.assertNotContains(response, self.submit_url(match))


class SubmitScoreTimingTests(RelativeMatches):
    def stored(self, match):
        match.refresh_from_db()
        return match.home_score, match.away_score

    def test_scorekeeper_refused_before_the_match_starts(self):
        match = self.later()
        self.client.force_login(self.keeper)
        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method(self.submit_url(match), SCORE, follow=True)
                self.assertRedirects(response, reverse("matches:mine"))
                self.assertContains(response, "once the match starts")
        self.assertEqual(self.stored(match), (None, None))

    def test_scorekeeper_submits_while_the_match_is_under_way(self):
        match = self.under_way()
        self.client.force_login(self.keeper)
        response = self.client.post(self.submit_url(match), SCORE)
        self.assertRedirects(response, reverse("matches:detail", args=[match.pk]))
        self.assertEqual(self.stored(match), (2, 1))

    def test_scorekeeper_submits_only_once(self):
        match = self.played(home_score=3, away_score=3)
        self.client.force_login(self.keeper)
        for method in (self.client.get, self.client.post):
            response = method(self.submit_url(match), SCORE, follow=True)
            self.assertRedirects(response, reverse("matches:mine"))
            self.assertContains(response, "already submitted")
        self.assertEqual(self.stored(match), (3, 3))
        detail = self.client.get(reverse("matches:detail", args=[match.pk]))
        self.assertIsNone(detail.context["score_url"])
        # A League Admin still corrects it.
        self.client.force_login(self.admin)
        self.client.post(reverse("matches:score", args=[match.pk]), SCORE)
        self.assertEqual(self.stored(match), (2, 1))

    def test_second_submit_is_refused_under_the_lock(self):
        match = self.played()
        sheet = MatchSheet(match, QueryDict(urlencode(SCORE)), first_only=True)
        self.assertTrue(sheet.is_valid())
        Match.objects.filter(pk=match.pk).update(home_score=5, away_score=0)
        self.assertFalse(sheet.save())
        self.assertIn("already submitted", sheet.non_field_errors()[0])
        self.assertEqual(self.stored(match), (5, 0))

    def test_league_admin_cannot_record_before_the_start(self):
        match = self.later()
        self.client.force_login(self.admin)
        url = reverse("matches:score", args=[match.pk])
        for method in (self.client.get, self.client.post):
            response = method(url, SCORE, follow=True)
            self.assertRedirects(
                response, reverse("matches:manage") + f"?season={self.season.pk}"
            )
            self.assertContains(response, "once the match starts")
        self.assertNotContains(response, f'href="{url}"')
        self.assertEqual(self.stored(match), (None, None))

    def test_league_admin_can_correct_a_result_of_a_moved_match(self):
        match = self.later(home_score=1, away_score=0)
        self.client.force_login(self.admin)
        self.client.post(reverse("matches:score", args=[match.pk]), SCORE)
        self.assertEqual(self.stored(match), (2, 1))


class DrawRuleTests(RelativeMatches):
    def post(self, match, home, away):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse("matches:score", args=[match.pk]),
            {"home_score": home, "away_score": away},
        )

    def test_draws_are_allowed_by_default(self):
        match = self.played()
        self.post(match, 1, 1)
        match.refresh_from_db()
        self.assertTrue(match.has_result)

    def test_tie_is_rejected_when_the_sport_has_no_draws(self):
        self.soccer.allows_draws = False
        self.soccer.save()
        match = self.played()
        response = self.post(match, 1, 1)
        self.assertContains(response, "Soccer matches can&#x27;t end in a draw.")
        match.refresh_from_db()
        self.assertFalse(match.has_result)
        self.post(match, 2, 1)
        match.refresh_from_db()
        self.assertTrue(match.has_result)

    def test_league_admin_edits_the_rule(self):
        self.client.force_login(self.admin)
        url = reverse("teams:edit_sport", args=[self.soccer.pk])
        self.assertContains(self.client.get(url), "allows_draws")
        self.client.post(url, {"name": "Soccer"})
        self.soccer.refresh_from_db()
        self.assertFalse(self.soccer.allows_draws)


class TeamFormTests(RelativeMatches):
    def test_team_page_shows_the_last_five_newest_first(self):
        results = [(1, 0), (0, 1), (2, 2), (3, 0), (0, 2), (1, 1)]
        played = [
            self.played(days_ago=day, home_score=h, away_score=a)
            for day, (h, a) in enumerate(results, start=1)
        ]
        self.played(days_ago=1, home_score=9, away_score=0).cancel()
        self.played(days_ago=1)
        self.client.force_login(self.player)
        response = self.client.get(reverse("teams:detail", args=[self.home.pk]))
        form = response.context["team_form"]
        self.assertEqual([f.letter for f in form], ["W", "L", "D", "W", "L"])
        self.assertEqual([f.match_pk for f in form], [m.pk for m in played[:5]])
        self.assertContains(response, "pn-form-chip", count=5)
        away = self.client.get(reverse("teams:detail", args=[self.away.pk]))
        letters = [f.letter for f in away.context["team_form"]]
        self.assertEqual(letters, ["L", "W", "D", "L", "W"])

    def test_no_form_without_results(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse("teams:detail", args=[self.home.pk]))
        self.assertNotContains(response, "pn-form-chip")


class MatchesToScoreCardTests(RelativeMatches):
    def setUp(self):
        self.home_url = reverse("core:home")
        self.mine_url = reverse("matches:mine")

    def get_home(self, user):
        self.client.force_login(user)
        return self.client.get(self.home_url)

    def test_card_only_for_scorekeepers(self):
        self.played()
        self.assertContains(self.get_home(self.keeper), "Matches to score")
        for user in (self.player, self.admin, self.superuser):
            with self.subTest(user=user.username):
                self.assertNotContains(self.get_home(user), "Matches to score")

    def test_losing_the_role_removes_the_card(self):
        match = self.played()
        self.remove_role(self.keeper)
        response = self.get_home(self.keeper)
        self.assertNotContains(response, "Matches to score")
        self.assertNotContains(response, self.submit_url(match))

    def test_card_shows_the_count_and_the_next_three(self):
        waiting = [self.played(days_ago=days) for days in (4, 3, 2, 1)]
        upcoming = self.later()
        scored = self.played(days_ago=5, home_score=1, away_score=1)
        theirs = self.played(keeper=self.other_keeper)
        response = self.get_home(self.keeper)
        self.assertContains(response, '<span class="pn-num">4</span> waiting')
        for match in waiting[:3]:
            self.assertContains(response, self.submit_url(match))
        for match in (waiting[3], upcoming, scored, theirs):
            self.assertNotContains(response, self.submit_url(match))
        self.assertContains(response, "See all 4 in My matches")
        self.assertContains(response, f'<a href="{self.mine_url}">')
        self.assertNotContains(response, "All scores are in.")

    def test_card_rows_show_both_logos_and_no_second_primary_button(self):
        without = self.get_home(self.keeper).content.decode()
        self.played()
        response = self.get_home(self.keeper)
        html = response.content.decode()
        self.assertEqual(html.count("pn-logo") - without.count("pn-logo"), 2)
        self.assertEqual(html.count("btn-primary"), without.count("btn-primary"))
        self.assertContains(response, "Violets")
        self.assertContains(response, "Bobcats")

    def test_scorekeeper_with_nothing_to_score_sees_the_compact_state(self):
        self.later()
        self.played(home_score=1, away_score=0)
        response = self.get_home(self.keeper)
        self.assertContains(response, "Matches to score")
        self.assertContains(response, "All scores are in.")
        self.assertContains(response, f'href="{self.mine_url}">Go to My matches')
        self.assertNotContains(response, "waiting")
