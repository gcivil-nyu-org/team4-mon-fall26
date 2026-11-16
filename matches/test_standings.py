from teams.models import Division, Team

from .standings import counted_matches, rank_rows, standings_by_team
from .tests import MatchFixtures, at


class CountedMatchesTests(MatchFixtures):
    def test_counts_only_scheduled_matches_with_both_scores(self):
        scored = self.build(home_score=2, away_score=0)
        scored.save()
        self.build(starts_at=at(11, 18), ends_at=at(11, 20)).save()
        cancelled = self.build(starts_at=at(12, 18), ends_at=at(12, 20))
        cancelled.save()
        cancelled.cancel()
        self.assertEqual(list(counted_matches()), [scored])


class RankRowsTests(MatchFixtures):
    def test_sorts_by_points_then_wins_then_name(self):
        rows = rank_rows([self.home, self.away], [(self.home.pk, self.away.pk, 1, 1)])
        self.assertEqual([r["team"].name for r in rows], ["Bobcats", "Violets"])
        self.assertEqual(rows[0]["points"], 1)

    def test_skips_scores_for_unknown_teams(self):
        rows = rank_rows([self.home], [(self.home.pk, self.away.pk, 2, 0)])
        self.assertEqual(rows[0]["played"], 0)


class StandingsByTeamTests(MatchFixtures):
    def test_matches_compute_standings(self):
        self.build(home_score=2, away_score=0).save()
        result = standings_by_team([self.season.pk, self.other_season.pk])
        from .standings import compute_standings

        for position, row in enumerate(compute_standings(self.season), start=1):
            self.assertEqual(result[row["team"].pk]["position"], position)
            self.assertEqual(result[row["team"].pk]["row"], row)
        self.assertEqual(result[self.home.pk]["of"], 3)
        self.assertEqual(result[self.outsider.pk]["position"], 1)

    def test_two_queries_for_any_number_of_seasons(self):
        with self.assertNumQueries(2):
            standings_by_team([self.season.pk, self.other_season.pk])

    def test_division_position(self):
        division = Division.objects.create(season=self.season, name="A")
        Team.objects.filter(pk=self.away.pk).update(division=division)
        result = standings_by_team([self.season.pk])
        self.assertEqual(result[self.away.pk]["division_position"], 1)
        self.assertEqual(result[self.away.pk]["division_of"], 1)
        self.assertIsNone(result[self.home.pk]["division_position"])

    def test_empty_input_runs_no_queries(self):
        with self.assertNumQueries(0):
            self.assertEqual(standings_by_team([]), {})
