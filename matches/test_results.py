from django.core.exceptions import ValidationError
from django.urls import reverse

from teams.models import Roster
from teams.season_rules import SeasonState

from .forms import ScoreForm
from .models import Match
from .standings import compute_standings
from .tests import MatchFixtures, ScorekeeperFixtures


class ScoreModelTests(MatchFixtures):
    def test_no_scores_by_default(self):
        match = self.build()
        match.full_clean()
        self.assertFalse(match.has_result)

    def test_both_scores_are_valid(self):
        match = self.build(home_score=2, away_score=1)
        match.full_clean()
        self.assertTrue(match.has_result)

    def test_zero_zero_is_a_played_draw(self):
        match = self.build(home_score=0, away_score=0)
        match.full_clean()
        self.assertTrue(match.has_result)

    def test_scores_come_in_pairs(self):
        for kwargs in ({"home_score": 2}, {"away_score": 1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError) as caught:
                    self.build(**kwargs).full_clean()
                self.assertIn("home_score", caught.exception.message_dict)
                self.assertIn("away_score", caught.exception.message_dict)

    def test_negative_scores_are_rejected(self):
        with self.assertRaises(ValidationError) as caught:
            self.build(home_score=-1, away_score=0).full_clean()
        self.assertIn("home_score", caught.exception.message_dict)

    def test_cancelled_matches_cannot_be_scored(self):
        match = self.build(home_score=2, away_score=1, status=Match.Status.CANCELLED)
        with self.assertRaises(ValidationError) as caught:
            match.full_clean()
        self.assertIn("home_score", caught.exception.message_dict)


class ScoreFormTests(MatchFixtures):
    def test_labels_name_the_teams(self):
        match = self.build()
        match.save()
        form = ScoreForm(instance=match)
        self.assertEqual(form.fields["home_score"].label, "Violets score")
        self.assertEqual(form.fields["away_score"].label, "Bobcats score")

    def test_requires_both_scores(self):
        match = self.build()
        match.save()
        form = ScoreForm({"home_score": "2"}, instance=match)
        self.assertFalse(form.is_valid())
        self.assertIn("away_score", form.errors)

    def test_rejects_negative_scores(self):
        match = self.build()
        match.save()
        form = ScoreForm({"home_score": "-1", "away_score": "0"}, instance=match)
        self.assertFalse(form.is_valid())
        self.assertIn("home_score", form.errors)

    def test_rejects_scores_outside_an_open_or_active_season(self):
        match = self.build()
        match.save()
        match.season.state = SeasonState.CLOSED
        match.season.save()
        form = ScoreForm(
            {"home_score": "2", "away_score": "1"},
            instance=Match.objects.select_related("season").get(pk=match.pk),
        )
        self.assertFalse(form.is_valid())


class RecordScorePermissionTests(MatchFixtures):
    def setUp(self):
        self.match = self.build()
        self.match.save()
        self.url = reverse("matches:score", args=[self.match.pk])

    def stored(self):
        self.match.refresh_from_db()
        return self.match.home_score, self.match.away_score

    def test_anonymous_redirected_to_login(self):
        response = self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_non_admin_gets_403(self):
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertEqual(self.stored(), (None, None))

    def test_admin_enters_the_score(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertRedirects(
            response, reverse("matches:manage") + f"?season={self.season.pk}"
        )
        self.assertEqual(self.stored(), (2, 1))

    def test_admin_correction_overwrites(self):
        self.match.home_score = 2
        self.match.away_score = 1
        self.match.save()
        self.client.force_login(self.admin)
        self.client.post(self.url, {"home_score": "0", "away_score": "0"})
        self.assertEqual(self.stored(), (0, 0))

    def test_cancelled_match_cannot_be_scored(self):
        self.match.cancel()
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertRedirects(
            response, reverse("matches:manage") + f"?season={self.season.pk}"
        )
        self.assertEqual(self.stored(), (None, None))

    def test_closed_season_blocks_scoring(self):
        self.season.state = SeasonState.CLOSED
        self.season.save()
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertRedirects(
            response, reverse("matches:manage") + f"?season={self.season.pk}"
        )
        self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertEqual(self.stored(), (None, None))


class SubmitScoreTests(ScorekeeperFixtures):
    def setUp(self):
        self.match = self.assign()
        self.url = reverse("matches:submit_score", args=[self.match.pk])

    def stored(self):
        self.match.refresh_from_db()
        return self.match.home_score, self.match.away_score

    def test_anonymous_redirected_to_login(self):
        response = self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_player_without_the_role_gets_403(self):
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertEqual(self.stored(), (None, None))

    def test_assigned_scorekeeper_submits(self):
        self.client.force_login(self.keeper)
        response = self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertRedirects(response, reverse("matches:mine"))
        self.assertEqual(self.stored(), (2, 1))

    def test_other_scorekeeper_gets_403(self):
        self.client.force_login(self.other_keeper)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertEqual(self.stored(), (None, None))

    def test_losing_the_role_blocks_submission(self):
        self.remove_role(self.keeper)
        self.client.force_login(self.keeper)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertEqual(self.stored(), (None, None))

    def test_cancelled_match_cannot_be_scored(self):
        self.match.cancel()
        self.client.force_login(self.keeper)
        response = self.client.post(self.url, {"home_score": "2", "away_score": "1"})
        self.assertRedirects(response, reverse("matches:mine"))
        self.assertEqual(self.stored(), (None, None))


class StandingsTests(MatchFixtures):
    def setUp(self):
        self.third = self.make_team("Terriers", self.soccer, self.season)

    def play(self, home, away, home_score, away_score, **overrides):
        match = self.build(
            home_team=home,
            away_team=away,
            home_score=home_score,
            away_score=away_score,
            **overrides,
        )
        match.save()
        return match

    def table(self):
        return {row["team"].name: row for row in compute_standings(self.season)}

    def test_win_is_three_points_and_draw_is_one(self):
        self.play(self.home, self.away, 2, 1)
        self.play(self.home, self.third, 1, 1)
        table = self.table()
        self.assertEqual(
            (
                table["Violets"]["played"],
                table["Violets"]["won"],
                table["Violets"]["points"],
            ),
            (2, 1, 4),
        )
        self.assertEqual(
            (table["Bobcats"]["lost"], table["Bobcats"]["points"]),
            (1, 0),
        )
        self.assertEqual(
            (table["Terriers"]["drawn"], table["Terriers"]["points"]),
            (1, 1),
        )

    def test_orders_by_points_then_wins_then_name(self):
        second = self.make_team("Aardvarks", self.soccer, self.season)
        self.play(self.home, self.away, 2, 0)
        self.play(second, self.third, 1, 0)
        self.play(second, self.third, 2, 0)
        names = [row["team"].name for row in compute_standings(self.season)]
        self.assertEqual(names[:2], ["Aardvarks", "Violets"])

    def test_ignores_cancelled_unscored_and_other_season_matches(self):
        cancelled = self.play(self.home, self.away, 5, 0)
        cancelled.cancel()
        self.play(self.home, self.away, None, None)
        self.build(
            season=self.other_season,
            home_team=self.outsider,
            away_team=self.make_team("Rivals", self.soccer, self.other_season),
            home_score=9,
            away_score=0,
        ).save()
        table = self.table()
        self.assertEqual(table["Violets"]["played"], 0)
        self.assertEqual(table["Bobcats"]["played"], 0)

    def test_teams_with_no_results_still_appear(self):
        self.play(self.home, self.away, 1, 0)
        table = self.table()
        self.assertEqual(
            (table["Terriers"]["played"], table["Terriers"]["points"]),
            (0, 0),
        )

    def test_corrections_recompute_the_table(self):
        match = self.play(self.home, self.away, 1, 0)
        match.home_score = 0
        match.away_score = 3
        match.save()
        table = self.table()
        self.assertEqual(table["Bobcats"]["points"], 3)
        self.assertEqual(table["Violets"]["points"], 0)


class ResultDisplayTests(ScorekeeperFixtures):
    def setUp(self):
        Roster.objects.create(team=self.home, player=self.player)
        self.match = self.build(home_score=2, away_score=1)
        self.match.save()

    def test_schedule_shows_the_score(self):
        self.client.force_login(self.player)
        response = self.client.get(
            reverse("matches:season_schedule", args=[self.season.pk])
        )
        self.assertContains(response, "2 – 1")

    def test_team_page_shows_the_score_and_record(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse("teams:detail", args=[self.home.pk]))
        self.assertContains(response, "2 – 1")
        self.assertContains(response, "1–0–0")

    def test_manage_page_shows_the_score(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("matches:manage") + f"?season={self.season.pk}"
        )
        self.assertContains(response, "2 – 1")

    def test_my_matches_shows_the_score(self):
        scored = self.assign(home_score=3, away_score=3)
        self.client.force_login(self.keeper)
        response = self.client.get(reverse("matches:mine"))
        self.assertContains(response, "3 – 3")
        self.assertEqual(response.context["matches"][0].pk, scored.pk)

    def test_standings_page_shows_points(self):
        self.client.force_login(self.player)
        response = self.client.get(
            reverse("matches:season_standings", args=[self.season.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pts")
        rows = {row["team"].name: row for row in response.context["rows"]}
        self.assertEqual(rows["Violets"]["points"], 3)

    def test_standings_list_links_to_the_season(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse("matches:standings"))
        self.assertContains(
            response, reverse("matches:season_standings", args=[self.season.pk])
        )

    def test_draft_season_standings_hidden_from_players(self):
        self.season.state = SeasonState.DRAFT
        self.season.save()
        self.client.force_login(self.player)
        self.assertEqual(
            self.client.get(
                reverse("matches:season_standings", args=[self.season.pk])
            ).status_code,
            404,
        )
