import datetime
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.management.commands.seed_demo_users import DEMO_USERS
from facilities.models import Facility
from teams.models import Roster, Season, Sport, Team
from teams.season_rules import SeasonState

from .management.commands.seed_demo_league import DEMO_TEAMS, round_robin
from .models import Match
from .standings import compute_standings

TODAY = "2026-11-13"
DEMO_NAMES = [name for name, _, _ in DEMO_TEAMS]
ENV = {"SEED_DEMO_LEAGUE": "1"}


def seed(*args, today=TODAY):
    out = StringIO()
    call_command("seed_demo_league", "--today", today, *args, stdout=out)
    return out.getvalue().strip()


def snapshot(model):
    return list(model.objects.order_by("pk").values())


class RoundRobinTests(SimpleTestCase):
    def test_every_pair_plays_once(self):
        for count in (2, 3, 4, 5):
            teams = list(range(count))
            pairs = round_robin(teams)
            self.assertEqual(
                sorted(tuple(sorted(pair)) for pair in pairs),
                [(a, b) for a in teams for b in teams if a < b],
            )

    def test_fewer_than_two_teams_have_no_matches(self):
        self.assertEqual(round_robin([]), [])
        self.assertEqual(round_robin(["only"]), [])

    def test_demo_teams_use_each_demo_player_at_most_once(self):
        emails = [email for _, _, members in DEMO_TEAMS for email in members]
        self.assertEqual(len(emails), len(set(emails)))
        self.assertLessEqual(set(emails), {email for email, _, _ in DEMO_USERS})


class SeedDemoLeagueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.soccer = Sport.objects.create(name="Soccer")
        cls.basketball = Sport.objects.create(name="Basketball")
        call_command("seed_semester_seasons", "--today", TODAY, stdout=StringIO())
        with mock.patch.dict("os.environ", {"DEMO_USERS_PASSWORD": "demo-pass-123"}):
            call_command("seed_demo_users", stdout=StringIO())
        cls.field = Facility.objects.create(name="Pier 40", source=Facility.Source.NYU)
        cls.field.sports.add(cls.soccer)
        cls.court = Facility.objects.create(
            name="Paulson Center", source=Facility.Source.NYU
        )
        cls.court.sports.add(cls.basketball)
        cls.season = Season.objects.get(sport=cls.soccer, term="2026-fall")

    @mock.patch.dict("os.environ", {}, clear=True)
    def test_does_nothing_without_the_variable_or_force(self):
        self.assertEqual(seed(), "SEED_DEMO_LEAGUE not set; no demo league seeded.")
        self.assertFalse(Team.objects.exists())
        self.assertFalse(Match.objects.exists())

    @mock.patch.dict("os.environ", {}, clear=True)
    def test_force_runs_without_the_variable(self):
        self.assertEqual(
            seed("--force"),
            "Demo league: 8 teams and 12 matches created in 2 seasons.",
        )

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_creates_teams_with_captains_and_rosters(self):
        self.assertEqual(
            seed(), "Demo league: 8 teams and 12 matches created in 2 seasons."
        )
        # Only this semester's seasons get teams: next semester's are drafts.
        self.assertFalse(Team.objects.exclude(season__term="2026-fall").exists())
        teams = Team.objects.filter(season=self.season).order_by("name")
        self.assertEqual([team.name for team in teams], sorted(DEMO_NAMES))
        self.assertEqual(
            set(teams.values_list("division__name", flat=True)),
            {"University-wide", "CAS"},
        )
        for team in teams:
            with self.subTest(team=team.name):
                self.assertEqual(team.sport, self.soccer)
                self.assertEqual(team.roster.count(), 3)
                captain = team.roster.get(role=Roster.Role.CAPTAIN)
                self.assertEqual(captain.player, team.captain)
        players = Roster.objects.filter(team__season=self.season).values_list(
            "player", flat=True
        )
        self.assertEqual(len(players), len(set(players)))

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_half_the_matches_are_played_and_half_upcoming(self):
        seed()
        matches = Match.objects.filter(season=self.season)
        self.assertEqual(matches.count(), 6)
        today = timezone.make_aware(
            datetime.datetime.combine(datetime.date(2026, 11, 13), datetime.time())
        )
        played = [match for match in matches if match.has_result]
        upcoming = [match for match in matches if not match.has_result]
        self.assertEqual((len(played), len(upcoming)), (3, 3))
        self.assertTrue(all(match.ends_at < today for match in played))
        self.assertTrue(
            all(
                match.starts_at > today + datetime.timedelta(days=1)
                for match in upcoming
            )
        )
        for match in matches:
            self.assertEqual(match.status, Match.Status.SCHEDULED)
            self.assertEqual(match.facility, self.field)
            self.assertEqual(match.home_team.season, self.season)
            match.full_clean()
        # No team plays two matches at once, and no facility hosts two.
        starts = list(Match.objects.values_list("facility", "starts_at"))
        self.assertEqual(len(starts), len(set(starts)))

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_standings_have_results(self):
        seed()
        for season in Season.objects.filter(term="2026-fall"):
            rows = compute_standings(season)
            self.assertEqual(len(rows), 4)
            self.assertEqual(sum(row["played"] for row in rows), 6)
            self.assertGreater(rows[0]["points"], 0)

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_second_run_creates_nothing(self):
        seed()
        teams, rosters, matches = (
            snapshot(Team),
            snapshot(Roster),
            snapshot(Match),
        )
        self.assertEqual(
            seed(today="2026-11-20"),
            "Demo league: 0 teams and 0 matches created in 2 seasons.",
        )
        self.assertEqual(snapshot(Team), teams)
        self.assertEqual(snapshot(Roster), rosters)
        self.assertEqual(snapshot(Match), matches)

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_runs_are_reproducible(self):
        def results():
            return list(
                Match.objects.order_by("season__name", "starts_at").values_list(
                    "home_team__name", "away_team__name", "home_score", "away_score"
                )
            )

        seed()
        first = results()
        Match.objects.all().delete()
        Team.objects.all().delete()
        seed()
        self.assertEqual(results(), first)

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_real_teams_and_matches_are_untouched(self):
        User = get_user_model()
        owner = User.objects.create_user("real@nyu.edu")
        rival = User.objects.create_user("rival@nyu.edu")
        demo_player = User.objects.get(username="demo.player1@nyu.edu")
        # A real team that took a demo team's name, and one a demo player joined.
        namesake = Team.objects.create(
            name="Demo Arches", sport=self.soccer, season=self.season, captain=owner
        )
        Roster.objects.create(team=namesake, player=owner, role=Roster.Role.CAPTAIN)
        real = Team.objects.create(
            name="Real FC", sport=self.soccer, season=self.season, captain=rival
        )
        Roster.objects.create(team=real, player=rival, role=Roster.Role.CAPTAIN)
        Roster.objects.create(team=real, player=demo_player)
        start = timezone.make_aware(datetime.datetime(2026, 11, 10, 18, 0))
        Match.objects.create(
            season=self.season,
            home_team=namesake,
            away_team=real,
            facility=self.field,
            starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
            home_score=5,
            away_score=0,
        )
        real_pks = [namesake.pk, real.pk]
        teams = list(Team.objects.filter(pk__in=real_pks).order_by("pk").values())
        rosters = list(Roster.objects.filter(team__in=real_pks).order_by("pk").values())
        matches = snapshot(Match)

        seed()

        self.assertEqual(
            list(Team.objects.filter(pk__in=real_pks).order_by("pk").values()), teams
        )
        self.assertEqual(
            list(Roster.objects.filter(team__in=real_pks).order_by("pk").values()),
            rosters,
        )
        self.assertEqual(
            list(Match.objects.filter(home_team=namesake).order_by("pk").values()),
            matches,
        )
        # The other three demo teams exist and play only each other.
        demo = Team.objects.filter(season=self.season).exclude(pk__in=real_pks)
        self.assertEqual(demo.count(), 3)
        demo_matches = Match.objects.filter(season=self.season).exclude(
            home_team=namesake
        )
        self.assertEqual(demo_matches.count(), 3)
        for match in demo_matches:
            self.assertIn(match.home_team, demo)
            self.assertIn(match.away_team, demo)
        # The demo player stays on the real team only.
        self.assertEqual(
            list(
                Roster.objects.filter(
                    player=demo_player, team__season=self.season
                ).values_list("team", flat=True)
            ),
            [real.pk],
        )
        self.assertEqual(
            Team.objects.get(name="Demo Violets", season=self.season).roster.count(), 2
        )

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_missing_matches_are_added_to_existing_teams(self):
        seed()
        kept = Match.objects.filter(season=self.season).first()
        Match.objects.filter(season=self.season).exclude(pk=kept.pk).delete()
        self.assertEqual(
            seed(), "Demo league: 0 teams and 5 matches created in 2 seasons."
        )
        self.assertEqual(Match.objects.filter(season=self.season).count(), 6)

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_draft_and_closed_seasons_get_nothing(self):
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.DRAFT)
        Season.objects.filter(sport=self.basketball, term="2026-fall").update(
            state=SeasonState.CLOSED
        )
        self.assertEqual(
            seed(), "Demo league: 0 teams and 0 matches created in 2 seasons."
        )

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_active_season_gets_matches_but_no_new_teams(self):
        seed()
        Match.objects.all().delete()
        Team.objects.filter(season=self.season, name="Demo Arches").delete()
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.ACTIVE)
        self.assertEqual(
            seed(), "Demo league: 0 teams and 9 matches created in 2 seasons."
        )
        self.assertEqual(Team.objects.filter(season=self.season).count(), 3)

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_without_facilities_teams_are_created_but_not_matches(self):
        Facility.objects.all().delete()
        output = seed()
        self.assertIn("Fall 2026 Soccer: no facility, so no matches.", output)
        self.assertIn("8 teams and 0 matches", output)

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_any_active_facility_is_used_when_none_lists_the_sport(self):
        self.field.sports.clear()
        Facility.objects.filter(pk=self.court.pk).update(is_active=False)
        seed()
        self.assertEqual(
            set(Match.objects.values_list("facility", flat=True)), {self.field.pk}
        )

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_without_demo_players_nothing_is_created(self):
        get_user_model().objects.all().delete()
        self.assertEqual(seed(), "No demo players; run seed_demo_users first.")
        self.assertFalse(Team.objects.exists())
