from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from teams.models import EventType, Roster

from .models import MatchAppearance, MatchPeriodScore, PlayerStat
from .tests import MatchFixtures, make_user


class MatchStatModelTests(MatchFixtures):
    def setUp(self):
        self.match = self.build()
        self.match.save()
        self.alex = make_user("alex")
        Roster.objects.create(team=self.home, player=self.alex)
        self.goal = EventType.objects.create(sport=self.soccer, name="Goal")

    def stat(self, **overrides):
        values = dict(
            match=self.match,
            player=self.alex,
            team=self.home,
            event_type=self.goal,
            value=2,
        )
        values.update(overrides)
        return PlayerStat(**values)

    def test_period_unique_per_match(self):
        MatchPeriodScore.objects.create(
            match=self.match, period=1, home_points=1, away_points=0
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            MatchPeriodScore.objects.create(
                match=self.match, period=1, home_points=2, away_points=0
            )

    def test_period_must_be_at_least_1(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MatchPeriodScore.objects.create(
                match=self.match, period=0, home_points=1, away_points=0
            )

    def test_period_limit_is_count_plus_2(self):
        self.assertEqual(self.soccer.period_count, 4)
        MatchPeriodScore(
            match=self.match, period=6, home_points=0, away_points=0
        ).full_clean()
        with self.assertRaises(ValidationError) as caught:
            MatchPeriodScore(
                match=self.match, period=7, home_points=0, away_points=0
            ).full_clean()
        self.assertEqual(
            caught.exception.message_dict["period"],
            ["Matches have at most 2 overtime periods."],
        )

    def test_stat_needs_roster_player(self):
        stranger = make_user("stranger")
        with self.assertRaises(ValidationError) as caught:
            self.stat(player=stranger).full_clean()
        self.assertEqual(
            caught.exception.message_dict["player"],
            ["That player isn't on this team."],
        )

    def test_stat_team_must_be_in_match(self):
        with self.assertRaises(ValidationError) as caught:
            self.stat(team=self.hoops_team).full_clean()
        self.assertEqual(
            caught.exception.message_dict["team"], ["Choose a team in this match."]
        )

    def test_stat_event_type_same_sport(self):
        dunk = EventType.objects.create(sport=self.hoops, name="Dunk")
        with self.assertRaises(ValidationError) as caught:
            self.stat(event_type=dunk).full_clean()
        self.assertEqual(
            caught.exception.message_dict["event_type"],
            ["Choose an event type for this sport."],
        )

    def test_stat_unique(self):
        self.stat().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.stat(value=3).save()

    def test_valid_stat_cleans(self):
        self.stat().full_clean()

    def test_left_player_row_still_cleans(self):
        row = self.stat()
        row.full_clean()
        row.save()
        Roster.objects.filter(team=self.home, player=self.alex).delete()
        row.value = 5
        row.full_clean()

    def test_moving_a_left_player_row_is_checked(self):
        row = self.stat()
        row.save()
        Roster.objects.filter(team=self.home, player=self.alex).delete()
        row.team = self.away
        with self.assertRaises(ValidationError):
            row.full_clean()

    def test_appearance_same_rules(self):
        stranger = make_user("stranger")
        with self.assertRaises(ValidationError) as caught:
            MatchAppearance(
                match=self.match, player=stranger, team=self.home
            ).full_clean()
        self.assertIn("player", caught.exception.message_dict)
        appearance = MatchAppearance(match=self.match, player=self.alex, team=self.home)
        appearance.full_clean()
        appearance.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MatchAppearance.objects.create(
                match=self.match, player=self.alex, team=self.home
            )

    def test_event_type_with_stats_is_protected(self):
        self.stat().save()
        with self.assertRaises(ProtectedError):
            self.goal.delete()

    def period(self, period):
        return MatchPeriodScore.objects.create(
            match=self.match, period=period, home_points=1, away_points=0
        )

    def assert_period_count_locked(self):
        with self.assertRaises(ValidationError) as caught:
            self.soccer.full_clean()
        self.assertEqual(
            caught.exception.message_dict,
            {
                "period_count": [
                    "Matches of this sport already have period scores. "
                    "A new period count would relabel them."
                ]
            },
        )

    def test_sport_cannot_drop_period_count_with_stored_periods(self):
        # 4 to 2 would show Q3 and Q4 as OT1 and OT2.
        self.period(3)
        self.soccer.period_count = 2
        self.assert_period_count_locked()

    def test_sport_cannot_raise_period_count_with_stored_periods(self):
        # 2 to 4 would show OT1 as Q3, and OT2 rows could no longer be saved.
        self.soccer.period_count = 2
        self.soccer.save()
        self.period(4)
        self.soccer.period_count = 4
        self.assert_period_count_locked()

    def test_sport_period_count_changes_without_stored_periods(self):
        self.soccer.period_count = 2
        self.soccer.save()
        self.soccer.refresh_from_db()
        self.assertEqual(self.soccer.period_count, 2)
        # Another sport's periods don't lock this one.
        rivals = self.make_team("Rivals", self.hoops, self.season)
        hoops_match = self.build(home_team=self.hoops_team, away_team=rivals)
        hoops_match.save()
        MatchPeriodScore.objects.create(
            match=hoops_match, period=1, home_points=1, away_points=0
        )
        self.soccer.period_count = 4
        self.soccer.full_clean()

    def test_sport_keeps_period_count_with_stored_periods(self):
        self.period(1)
        self.soccer.period_label = "Half"
        self.soccer.full_clean()
