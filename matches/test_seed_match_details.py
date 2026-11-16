import json
import os
import random
import tempfile
from collections import defaultdict
from io import StringIO
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from accounts.placeholders import placeholder_for
from audit.models import AuditLog
from facilities.models import Facility
from notifications.models import Notification
from teams.models import EventType, Roster, Season, Sport
from teams.season_rules import SeasonState

from .management.commands.seed_match_details import split_total
from .models import Match, MatchAppearance, MatchPeriodScore, PlayerStat
from .standings import compute_standings
from .stats import save_match_sheet
from .test_seed_class_league import SPORTS, TODAY, roster_data

EVENT_TYPES = {
    "Basketball": ["Points", "Assists", "Rebounds"],
    "Futsal": ["Goals", "Assists", "Yellow cards"],
    "Volleyball": ["Points", "Aces", "Kills"],
}


def details():
    """Every detail row, without pks, so two runs can be compared."""
    return (
        sorted(
            MatchPeriodScore.objects.values_list(
                "match_id", "period", "home_points", "away_points"
            )
        ),
        sorted(
            PlayerStat.objects.values_list(
                "match_id", "team_id", "player_id", "event_type_id", "value"
            )
        ),
        sorted(MatchAppearance.objects.values_list("match_id", "team_id", "player_id")),
    )


def scores():
    return list(
        Match.objects.order_by("pk").values_list(
            "pk", "status", "home_score", "away_score"
        )
    )


def table(season):
    return [
        (row["team"].pk, row["played"], row["won"], row["drawn"], row["lost"])
        + (row["points"],)
        for row in compute_standings(season)
    ]


class SplitTotalTests(SimpleTestCase):
    def test_parts_add_up_exactly(self):
        rng = random.Random(3)
        for total in [0, 1, 3, 7, 45, 80]:
            for parts in [1, 2, 4]:
                split = split_total(rng, total, parts)
                self.assertEqual(len(split), parts)
                self.assertEqual(sum(split), total)
                self.assertTrue(all(part >= 0 for part in split))


class SeededLeagueTestCase(TestCase):
    """The class league, scored, with EVENT_TYPES. It holds no tests."""

    @classmethod
    def setUpTestData(cls):
        for name in SPORTS:
            sport = Sport.objects.create(name=name)
            for event_type in EVENT_TYPES[name]:
                EventType.objects.create(sport=sport, name=event_type)
        Sport.objects.filter(name="Basketball").update(period_count=4)
        Sport.objects.filter(name="Futsal").update(period_count=2, period_label="Half")
        Sport.objects.filter(name="Volleyball").update(
            period_count=5, period_label="Set"
        )
        call_command("seed_semester_seasons", "--today", TODAY, stdout=StringIO())
        for number in range(3):
            facility = Facility.objects.create(
                name=f"Court {number}", source=Facility.Source.NYU
            )
            facility.sports.add(*Sport.objects.all())
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        try:
            with open(path, "w", encoding="utf-8") as out:
                json.dump(roster_data(), out)
            call_command(
                "seed_class_league",
                "--roster",
                path,
                "--today",
                TODAY,
                stdout=StringIO(),
            )
        finally:
            os.remove(path)

    def run_command(self, *args):
        out = StringIO()
        call_command("seed_match_details", *args, stdout=out, stderr=out)
        return out.getvalue()

    def season(self, sport):
        return Season.objects.get(sport__name=sport, term="2026-fall")

    def scored(self, sport):
        return Match.objects.filter(
            season=self.season(sport), home_score__isnull=False
        ).select_related("home_team", "away_team")

    def event_type(self, sport, name):
        return EventType.objects.get(sport__name=sport, name=name)

    def assert_stats_match_score(self, sport, scoring):
        points = self.event_type(sport, scoring)
        assists = self.event_type(sport, "Assists") if sport != "Volleyball" else None
        for match in self.scored(sport):
            played = defaultdict(set)
            for team_id, player_id in MatchAppearance.objects.filter(
                match=match
            ).values_list("team_id", "player_id"):
                played[team_id].add(player_id)
            for team, score in [
                (match.home_team, match.home_score),
                (match.away_team, match.away_score),
            ]:
                self.assertGreaterEqual(len(played[team.pk]), 1)
                roster = set(
                    Roster.objects.filter(team=team).values_list("player_id", flat=True)
                )
                self.assertLessEqual(played[team.pk], roster)
                stats = PlayerStat.objects.filter(match=match, team=team)
                self.assertLessEqual(
                    set(stats.values_list("player_id", flat=True)), played[team.pk]
                )
                goals = sum(
                    stats.filter(event_type=points).values_list("value", flat=True)
                )
                self.assertEqual(goals, score)
                if assists:
                    given = sum(
                        stats.filter(event_type=assists).values_list("value", flat=True)
                    )
                    self.assertLessEqual(given, goals)


class SeedMatchDetailsTests(SeededLeagueTestCase):
    def test_basketball_quarters_and_points_add_up(self):
        output = self.run_command()
        self.assertIn("Basketball: updated 18 matches", output)
        for match in self.scored("Basketball"):
            periods = list(
                match.period_scores.values_list("home_points", "away_points")
            )
            self.assertEqual(len(periods), 4)
            self.assertEqual(sum(home for home, _ in periods), match.home_score)
            self.assertEqual(sum(away for _, away in periods), match.away_score)
        self.assert_stats_match_score("Basketball", "Points")
        rebounds = self.event_type("Basketball", "Rebounds")
        self.assertTrue(PlayerStat.objects.filter(event_type=rebounds).exists())

    def test_futsal_halves_and_goals_add_up(self):
        self.run_command()
        for match in self.scored("Futsal"):
            periods = list(
                match.period_scores.values_list("home_points", "away_points")
            )
            self.assertEqual(len(periods), 2)
            self.assertEqual(sum(home for home, _ in periods), match.home_score)
            self.assertEqual(sum(away for _, away in periods), match.away_score)
        self.assert_stats_match_score("Futsal", "Goals")

    def test_volleyball_gets_no_sets_and_no_points(self):
        # The final score is sets won. Set points can't add up to it.
        output = self.run_command()
        self.assertIn("Volleyball: updated 18 matches", output)
        self.assertIn("Volleyball: the final score counts sets won", output)
        volleyball = self.scored("Volleyball")
        self.assertFalse(MatchPeriodScore.objects.filter(match__in=volleyball).exists())
        points = self.event_type("Volleyball", "Points")
        self.assertFalse(PlayerStat.objects.filter(event_type=points).exists())
        kills = self.event_type("Volleyball", "Kills")
        self.assertTrue(PlayerStat.objects.filter(event_type=kills).exists())
        for match in volleyball:
            teams = set(match.appearances.values_list("team_id", flat=True))
            self.assertEqual(teams, {match.home_team_id, match.away_team_id})

    def test_sport_with_no_event_types_gets_periods_and_appearances(self):
        PlayerStat.objects.all().delete()
        EventType.objects.filter(sport__name="Futsal").delete()
        output = self.run_command()
        self.assertIn(
            "Futsal: no event types; recorded periods and appearances only.", output
        )
        futsal = self.scored("Futsal")
        self.assertFalse(PlayerStat.objects.filter(match__in=futsal).exists())
        self.assertTrue(MatchAppearance.objects.filter(match__in=futsal).exists())
        self.assertEqual(
            MatchPeriodScore.objects.filter(match__in=futsal).count(),
            2 * futsal.count(),
        )

    def test_rerun_changes_nothing(self):
        self.run_command()
        first = details()
        output = self.run_command()
        self.assertEqual(details(), first)
        self.assertIn("Updated 0 matches.", output)
        self.assertIn("54 already have details", output)

    def test_same_seed_gives_the_same_details(self):
        self.run_command("--seed", "7")
        first = details()
        MatchPeriodScore.objects.all().delete()
        PlayerStat.objects.all().delete()
        MatchAppearance.objects.all().delete()
        self.run_command("--seed", "7")
        self.assertEqual(details(), first)
        MatchPeriodScore.objects.all().delete()
        PlayerStat.objects.all().delete()
        MatchAppearance.objects.all().delete()
        self.run_command("--seed", "8")
        self.assertNotEqual(details(), first)

    def test_match_with_details_is_untouched(self):
        match = self.scored("Futsal").first()
        player = Roster.objects.filter(team=match.home_team).first().player
        MatchAppearance.objects.create(match=match, team=match.home_team, player=player)
        output = self.run_command()
        self.assertEqual(match.appearances.count(), 1)
        self.assertFalse(match.period_scores.exists())
        self.assertFalse(match.player_stats.exists())
        self.assertIn("Futsal: updated 17 matches", output)
        self.assertIn("1 already have details", output)

    def test_cancelled_and_unscored_matches_are_untouched(self):
        season = self.season("Basketball")
        upcoming = Match.objects.filter(season=season, home_score__isnull=True)
        cancelled = upcoming.first()
        cancelled.cancel()
        output = self.run_command()
        for match in Match.objects.filter(pk__in=upcoming):
            self.assertFalse(match.period_scores.exists())
            self.assertFalse(match.appearances.exists())
            self.assertFalse(match.player_stats.exists())
        self.assertIn("1 cancelled", output)
        self.assertIn("no final score", output)

    def test_dry_run_writes_nothing(self):
        output = self.run_command("--dry-run")
        self.assertIn("Basketball: would update 18 matches", output)
        self.assertIn("Dry run: nothing saved.", output)
        self.assertEqual(details(), ([], [], []))

    def test_standings_scores_notifications_and_audit_unchanged(self):
        before_scores = scores()
        before_tables = {sport: table(self.season(sport)) for sport in SPORTS}
        notifications = Notification.objects.count()
        audits = AuditLog.objects.count()
        self.run_command()
        self.assertEqual(scores(), before_scores)
        for sport in SPORTS:
            self.assertEqual(table(self.season(sport)), before_tables[sport])
        self.assertEqual(Notification.objects.count(), notifications)
        self.assertEqual(AuditLog.objects.count(), audits)

    def test_season_option_limits_the_run(self):
        basketball = self.season("Basketball")
        output = self.run_command("--season", str(basketball.pk))
        self.assertIn("Basketball: updated 18 matches", output)
        self.assertNotIn("Futsal", output)
        self.assertEqual(
            set(MatchAppearance.objects.values_list("match__season", flat=True)),
            {basketball.pk},
        )
        with self.assertRaisesMessage(CommandError, "No season with pk 999999."):
            self.run_command("--season", "999999")

    def test_closed_season_is_filled_and_draft_season_skipped(self):
        Season.objects.filter(pk=self.season("Basketball").pk).update(
            state=SeasonState.CLOSED
        )
        Season.objects.filter(pk=self.season("Futsal").pk).update(
            state=SeasonState.DRAFT
        )
        output = self.run_command()
        self.assertIn("Basketball: updated 18 matches", output)
        self.assertFalse(
            MatchAppearance.objects.filter(match__season__sport__name="Futsal").exists()
        )
        self.assertIn("draft season", output)

    def test_team_with_no_players_is_skipped(self):
        match = self.scored("Futsal").first()
        Roster.objects.filter(team=match.home_team).delete()
        output = self.run_command()
        self.assertFalse(match.appearances.exists())
        self.assertIn("a team has no roster players", output)

    def test_queries_per_match_stay_bounded(self):
        basketball = self.season("Basketball")
        futsal = self.season("Futsal")
        with CaptureQueriesContext(connection) as small:
            self.run_command("--season", str(futsal.pk))
        # Bigger rosters must not add queries.
        team = Match.objects.filter(season=basketball).first().home_team
        for number in range(6):
            user, _ = placeholder_for(f"extra{number}@nyu.edu")
            Roster.objects.create(team=team, player=user)
        with CaptureQueriesContext(connection) as large:
            self.run_command("--season", str(basketball.pk))
        # 18 scored matches in each season: a fixed cost plus 16 or fewer per match.
        self.assertLessEqual(len(small.captured_queries), 10 + 16 * 18)
        self.assertEqual(len(large.captured_queries), len(small.captured_queries))

    def test_sport_with_no_scoring_type_gets_the_other_stats(self):
        EventType.objects.filter(sport__name="Futsal", name="Goals").delete()
        output = self.run_command("--verbosity", "2")
        self.assertIn("Futsal: no scoring event type", output)
        self.assertRegex(output, r"Match \d+ \(.+\): 2 periods, \d+ appearances")
        assists = self.event_type("Futsal", "Assists")
        for match in self.scored("Futsal"):
            for team_id, score in [
                (match.home_team_id, match.home_score),
                (match.away_team_id, match.away_score),
            ]:
                given = sum(
                    PlayerStat.objects.filter(
                        match=match, team_id=team_id, event_type=assists
                    ).values_list("value", flat=True)
                )
                self.assertLessEqual(given, score)

    def test_refused_match_is_rolled_back_and_reported(self):
        def refuse(match, **kwargs):
            MatchAppearance.objects.create(
                match=match,
                team=match.home_team,
                player=Roster.objects.filter(team=match.home_team).first().player,
            )
            raise ValidationError("Nope.")

        before = scores()
        target = "matches.management.commands.seed_match_details.save_match_sheet"
        with mock.patch(target, side_effect=refuse):
            output = self.run_command("--season", str(self.season("Futsal").pk))
        self.assertIn("18 refused (Nope.)", output)
        self.assertEqual(details(), ([], [], []))
        self.assertEqual(scores(), before)

    def test_writer_refuses_closed_seasons_unless_asked(self):
        match = self.scored("Futsal").first()
        Season.objects.filter(pk=match.season_id).update(state=SeasonState.CLOSED)
        match = Match.objects.get(pk=match.pk)
        sheet = {
            "periods": [],
            "final": (match.home_score, match.away_score),
            "stats": {},
            "played": set(),
            "players": set(),
        }
        with self.assertRaisesMessage(ValidationError, "can no longer be scored"):
            save_match_sheet(match, **sheet)
        save_match_sheet(match, allow_closed=True, **sheet)
        match.cancel()
        with self.assertRaisesMessage(ValidationError, "can no longer be scored"):
            save_match_sheet(match, allow_closed=True, **sheet)

    def test_seed_uses_the_marked_scoring_type(self):
        # Rebounds is marked, so it adds up to the score; Points is a plain stat.
        EventType.objects.filter(sport__name="Basketball", name="Rebounds").update(
            is_scoring=True
        )
        self.run_command("--season", str(self.season("Basketball").pk))
        self.assert_stats_match_score("Basketball", "Rebounds")

    def test_marked_type_beats_the_name_fallback(self):
        # Goals is the name fallback; the mark on Yellow cards wins over it.
        EventType.objects.filter(sport__name="Futsal", name="Yellow cards").update(
            is_scoring=True
        )
        self.run_command("--season", str(self.season("Futsal").pk))
        cards = self.event_type("Futsal", "Yellow cards")
        goals = self.event_type("Futsal", "Goals")
        goal_totals = []
        for match in self.scored("Futsal"):
            stats = PlayerStat.objects.filter(match=match)
            total = sum(stats.filter(event_type=cards).values_list("value", flat=True))
            self.assertEqual(total, match.home_score + match.away_score)
            goal_totals.append(
                sum(stats.filter(event_type=goals).values_list("value", flat=True))
            )
        finals = [m.home_score + m.away_score for m in self.scored("Futsal")]
        self.assertNotEqual(goal_totals, finals)


class DefaultEventTypesCommandTests(SeededLeagueTestCase):
    """--default-event-types on a league with no event types."""

    def setUp(self):
        EventType.objects.all().delete()

    def types(self):
        return sorted(
            EventType.objects.values_list("sport__name", "name", "is_scoring")
        )

    def test_creates_types_only_for_empty_sports(self):
        futsal = Sport.objects.get(name="Futsal")
        EventType.objects.create(sport=futsal, name="Fouls")

        output = self.run_command("--default-event-types")

        self.assertEqual(
            self.types(),
            [
                ("Basketball", "Assists", False),
                ("Basketball", "Points", True),
                ("Basketball", "Rebounds", False),
                ("Futsal", "Fouls", False),
                ("Volleyball", "Aces", False),
                ("Volleyball", "Kills", False),
            ],
        )
        self.assertIn(
            "Basketball: created event types Points, Assists, Rebounds "
            "(scoring stat: Points).",
            output,
        )
        self.assertIn(
            "Volleyball: created event types Kills, Aces (no scoring stat).", output
        )
        self.assertNotIn("Futsal: created", output)

    def test_rerun_creates_nothing(self):
        self.run_command("--default-event-types")
        first = self.types()
        first_details = details()

        output = self.run_command("--default-event-types")

        self.assertEqual(self.types(), first)
        self.assertEqual(details(), first_details)
        self.assertIn("Created 0 event types.", output)

    def test_dry_run_writes_nothing(self):
        output = self.run_command("--default-event-types", "--dry-run")

        self.assertFalse(EventType.objects.exists())
        self.assertEqual(details(), ([], [], []))
        self.assertIn("Basketball: would create event types Points", output)
        self.assertIn("Would create 8 event types.", output)
        # The run counts the stats it would add with the new types.
        self.assertRegex(
            output, r"Basketball: would update 18 matches .* [1-9]\d* player"
        )
        self.assertIn("Dry run: nothing saved.", output)

    def test_default_points_add_up_to_the_final_score(self):
        self.run_command("--default-event-types")
        self.assert_stats_match_score("Basketball", "Points")
        self.assert_stats_match_score("Futsal", "Goals")
        kills = self.event_type("Volleyball", "Kills")
        self.assertTrue(PlayerStat.objects.filter(event_type=kills).exists())

    def test_without_the_option_no_types_are_created(self):
        output = self.run_command()
        self.assertFalse(EventType.objects.exists())
        self.assertNotIn("create", output.lower())
