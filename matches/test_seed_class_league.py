import datetime
import json
import os
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.models import PendingAccount
from audit.models import AuditLog
from facilities.models import Facility
from notifications.models import Notification
from teams.models import Roster, Season, Sport, Team
from teams.season_rules import SeasonState

from .management.commands.seed_class_league import (
    double_round_robin,
    ensure_leader_first,
    make_score,
    validate_roster,
)
from .models import Match
from .standings import compute_standings

TODAY = "2026-11-13"
SPORTS = ["Basketball", "Volleyball", "Futsal"]
KEYS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]


def roster_data(team_count=6, members=3, leader="alpha"):
    teams = []
    for key in KEYS[:team_count]:
        teams.append(
            {
                "key": key,
                "names": {sport: f"{key.title()} {sport}" for sport in SPORTS},
                "members": [
                    {
                        "first_name": key.title(),
                        "last_name": str(n),
                        "email": f"{key}{n}@nyu.edu",
                    }
                    for n in range(1, members + 1)
                ],
            }
        )
    return {
        "sports": list(SPORTS),
        "division": "University-wide",
        "leader": leader,
        "teams": teams,
    }


def snapshot(model):
    return list(model.objects.order_by("pk").values())


class ValidationTests(SimpleTestCase):
    def assertRejects(self, data, message):
        with self.assertRaisesMessage(CommandError, message):
            validate_roster(data)

    def test_valid_roster_passes(self):
        validate_roster(roster_data())
        validate_roster(roster_data(team_count=2))

    def test_needs_two_teams(self):
        self.assertRejects(roster_data(team_count=1), "two or more teams")

    def test_needs_a_name_for_every_sport(self):
        data = roster_data()
        del data["teams"][2]["names"]["Futsal"]
        self.assertRejects(data, 'Team "charlie" has no name for Futsal.')

    def test_rejects_a_non_nyu_email_and_names_only_that_one(self):
        data = roster_data()
        data["teams"][1]["members"][1]["email"] = "bravo2@gmail.com"
        with self.assertRaises(CommandError) as caught:
            validate_roster(data)
        message = str(caught.exception)
        self.assertIn('Team "bravo", member 2', message)
        self.assertIn("bravo2@gmail.com", message)
        self.assertNotIn("bravo1@nyu.edu", message)

    def test_rejects_a_duplicate_email_in_a_team_without_echoing_it(self):
        data = roster_data()
        data["teams"][0]["members"][2]["email"] = "ALPHA1@nyu.edu"
        with self.assertRaises(CommandError) as caught:
            validate_roster(data)
        message = str(caught.exception)
        self.assertIn("member 3 has the same email as member 1", message)
        self.assertNotIn("@", message)

    def test_leader_must_be_a_team_key(self):
        self.assertRejects(roster_data(leader="zulu"), '"leader" must be the key')

    def test_other_shape_errors(self):
        self.assertRejects([], "JSON object")
        self.assertRejects({**roster_data(), "sports": []}, '"sports"')
        self.assertRejects(
            {**roster_data(), "sports": ["Futsal", "futsal"]}, "sport twice"
        )
        self.assertRejects({**roster_data(), "division": ""}, '"division"')
        data = roster_data()
        data["teams"][1]["key"] = "alpha"
        self.assertRejects(data, "used twice")
        data = roster_data()
        data["teams"][1]["names"]["Futsal"] = "Alpha Futsal"
        self.assertRejects(data, "another team has its Futsal name")
        data = roster_data()
        data["teams"][1]["members"] = []
        self.assertRejects(data, "one or more members")
        data = roster_data()
        data["teams"][1]["names"] = None
        self.assertRejects(data, 'needs "names"')
        data = roster_data()
        data["teams"][1]["members"][0] = "bravo1@nyu.edu"
        self.assertRejects(data, "must be an object")
        data = roster_data()
        data["teams"][1]["members"][0]["first_name"] = 7
        self.assertRejects(data, '"first_name" must be text')
        data = roster_data()
        data["teams"][1] = "bravo"
        self.assertRejects(data, 'Team 2 needs a "key"')


class HelperTests(SimpleTestCase):
    def test_double_round_robin_plays_every_pair_home_and_away(self):
        teams = list(range(6))
        rounds = double_round_robin(teams)
        self.assertEqual(len(rounds), 10)
        self.assertTrue(all(len(pairs) == 3 for pairs in rounds))
        pairs = [pair for pairs in rounds for pair in pairs]
        self.assertEqual(
            sorted(pairs), [(a, b) for a in teams for b in teams if a != b]
        )

    def test_scores_follow_each_sport(self):
        import random

        rng = random.Random(1)
        for _ in range(200):
            home, away = make_score(rng, "Basketball")
            self.assertTrue(45 <= min(home, away) and max(home, away) <= 80)
            self.assertNotEqual(home, away)
            self.assertIn(
                sorted(make_score(rng, "Volleyball")), [[0, 3], [1, 3], [2, 3]]
            )
            home, away = make_score(rng, "Futsal")
            self.assertTrue(0 <= min(home, away) and max(home, away) <= 7)
            for sport in SPORTS:
                home, away = make_score(rng, sport, "away")
                self.assertGreater(away, home)


class SeedClassLeagueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for name in SPORTS + ["Soccer"]:
            Sport.objects.create(name=name)
        call_command("seed_semester_seasons", "--today", TODAY, stdout=StringIO())
        cls.facilities = []
        for number in range(3):
            facility = Facility.objects.create(
                name=f"Court {number}", source=Facility.Source.NYU
            )
            facility.sports.add(*Sport.objects.all())
            cls.facilities.append(facility)

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.addCleanup(os.remove, self.path)
        self.write(roster_data())

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as out:
            json.dump(data, out)

    def seed(self, *args, today=TODAY):
        out = StringIO()
        call_command(
            "seed_class_league",
            "--roster",
            self.path,
            "--today",
            today,
            *args,
            stdout=out,
            stderr=out,
        )
        return out.getvalue()

    def season(self, sport):
        return Season.objects.get(sport__name=sport, term="2026-fall")

    def test_bad_file_writes_nothing(self):
        data = roster_data()
        data["teams"][5]["members"][0]["email"] = "foxtrot1@example.com"
        self.write(data)
        with self.assertRaisesMessage(CommandError, "not an @nyu.edu email"):
            self.seed()
        self.assertFalse(get_user_model().objects.exists())
        with open(self.path, "w") as out:
            out.write("{not json")
        with self.assertRaisesMessage(CommandError, "not valid JSON"):
            self.seed()
        with self.assertRaisesMessage(CommandError, "Can't read"):
            call_command(
                "seed_class_league",
                "--roster",
                self.path + ".missing",
                stdout=StringIO(),
            )

    def test_creates_teams_rosters_and_placeholders(self):
        output = self.seed()
        self.assertIn(
            "Basketball (Fall 2026 Basketball): created 6 teams, 18 roster entries, "
            "18 placeholder accounts and 30 matches (18 played, 12 upcoming).",
            output,
        )
        self.assertNotIn("@", output)
        self.assertEqual(get_user_model().objects.count(), 18)
        self.assertEqual(PendingAccount.objects.count(), 18)
        self.assertFalse(Team.objects.exclude(season__term="2026-fall").exists())
        for sport in SPORTS:
            season = self.season(sport)
            teams = Team.objects.filter(season=season)
            self.assertEqual(teams.count(), 6)
            team = teams.get(name=f"Alpha {sport}")
            self.assertEqual(team.captain.email, "alpha1@nyu.edu")
            self.assertEqual(team.division.name, "University-wide")
            self.assertEqual(
                sorted(team.roster.values_list("player__email", "role")),
                [
                    ("alpha1@nyu.edu", Roster.Role.CAPTAIN),
                    ("alpha2@nyu.edu", Roster.Role.PLAYER),
                    ("alpha3@nyu.edu", Roster.Role.PLAYER),
                ],
            )
        self.assertFalse(Team.objects.filter(sport__name="Soccer").exists())

    def test_links_existing_users(self):
        User = get_user_model()
        active = User.objects.create_user(
            "bravo2@nyu.edu", email="bravo2@nyu.edu", first_name="Real"
        )
        self.seed()
        self.assertEqual(User.objects.count(), 18)
        self.assertEqual(PendingAccount.objects.count(), 17)
        active.refresh_from_db()
        self.assertTrue(active.is_active)
        self.assertEqual(active.first_name, "Real")
        self.assertEqual(Roster.objects.filter(player=active).count(), len(SPORTS))

    def test_member_on_another_team_is_skipped(self):
        season = self.season("Futsal")
        User = get_user_model()
        other = User.objects.create_user("charlie2@nyu.edu", email="charlie2@nyu.edu")
        owner = User.objects.create_user("owner@nyu.edu", email="owner@nyu.edu")
        team = Team.objects.create(
            name="Other FC", sport=season.sport, season=season, captain=owner
        )
        Roster.objects.create(team=team, player=owner, role=Roster.Role.CAPTAIN)
        Roster.objects.create(team=team, player=other)
        output = self.seed()
        self.assertIn(
            "Futsal: Charlie Futsal, member 2 is already on another team", output
        )
        self.assertNotIn("charlie2", output)
        self.assertEqual(
            Roster.objects.get(player=other, team__season=season).team, team
        )

    def test_played_and_upcoming_split_around_today(self):
        self.seed()
        now = timezone.make_aware(datetime.datetime(2026, 11, 13))
        end = timezone.make_aware(datetime.datetime(2026, 12, 16))
        slots = set()
        for sport in SPORTS:
            matches = list(Match.objects.filter(season=self.season(sport)))
            self.assertEqual(len(matches), 30)
            played = [match for match in matches if match.has_result]
            upcoming = [match for match in matches if not match.has_result]
            self.assertEqual((len(played), len(upcoming)), (18, 12))
            self.assertTrue(all(match.ends_at < now for match in played))
            self.assertTrue(all(now < match.starts_at < end for match in upcoming))
            last = max(match.starts_at for match in played)
            self.assertIn((now - last).days, (0, 1, 2))
            for match in matches:
                self.assertEqual(
                    match.ends_at - match.starts_at, datetime.timedelta(minutes=75)
                )
                match.full_clean()
                slots.add((match.facility_id, match.starts_at))
        # No facility hosts two matches at once.
        self.assertEqual(len(slots), 90)

    def test_upcoming_matches_stay_before_the_season_end(self):
        season = self.season("Basketball")
        season.end_date = datetime.date(2026, 11, 20)
        season.save()
        self.seed()
        matches = Match.objects.filter(season=season)
        latest = timezone.localtime(max(m.starts_at for m in matches)).date()
        self.assertLessEqual(latest, season.end_date)
        self.assertEqual(matches.filter(home_score__isnull=True).count(), 12)

    def test_leader_is_first_in_every_sport(self):
        self.seed()
        for sport in SPORTS:
            rows = compute_standings(self.season(sport))
            self.assertEqual(rows[0]["team"].name, f"Alpha {sport}")
            self.assertEqual(rows[0]["lost"] + rows[0]["drawn"], 0)
        basketball = Match.objects.filter(
            season=self.season("Basketball"), home_score__isnull=False
        )
        self.assertFalse(any(m.home_score == m.away_score for m in basketball))

    def test_odd_team_count_and_other_leader(self):
        self.write(roster_data(team_count=5, leader="echo"))
        self.seed()
        for sport in SPORTS:
            rows = compute_standings(self.season(sport))
            self.assertEqual(rows[0]["team"].name, f"Echo {sport}")

    def test_ensure_leader_first_makes_the_team_above_lose(self):
        season = self.season("Futsal")
        User = get_user_model()
        teams = {}
        for key in ("alpha", "bravo", "charlie", "delta"):
            captain = User.objects.create_user(f"{key}9@nyu.edu")
            teams[key] = Team.objects.create(
                name=key.title(), sport=season.sport, season=season, captain=captain
            )
        start = timezone.make_aware(datetime.datetime(2026, 11, 1, 18, 0))
        matches = []
        for day, (home, away, home_score, away_score) in enumerate(
            [
                ("alpha", "charlie", 2, 0),
                ("bravo", "charlie", 3, 1),
                ("alpha", "delta", 1, 0),
                ("delta", "bravo", 0, 1),
                ("charlie", "bravo", 0, 2),
            ]
        ):
            matches.append(
                Match.objects.create(
                    season=season,
                    home_team=teams[home],
                    away_team=teams[away],
                    facility=self.facilities[0],
                    starts_at=start + datetime.timedelta(days=day),
                    ends_at=start + datetime.timedelta(days=day, hours=1),
                    home_score=home_score,
                    away_score=away_score,
                )
            )
        self.assertEqual(compute_standings(season)[0]["team"], teams["bravo"])
        self.assertEqual(ensure_leader_first(season, teams["alpha"], matches), 1)
        self.assertEqual(compute_standings(season)[0]["team"], teams["alpha"])
        matches[1].refresh_from_db()
        self.assertEqual((matches[1].home_score, matches[1].away_score), (1, 3))
        # Matches with the leader never change.
        matches[0].refresh_from_db()
        self.assertEqual((matches[0].home_score, matches[0].away_score), (2, 0))
        self.assertEqual(ensure_leader_first(season, teams["alpha"], matches), 0)

    def test_ensure_leader_first_turns_a_draw_into_a_loss(self):
        season = self.season("Futsal")
        User = get_user_model()
        teams = {}
        for key in ("alpha", "bravo", "charlie", "delta"):
            captain = User.objects.create_user(f"{key}9@nyu.edu")
            teams[key] = Team.objects.create(
                name=key.title(), sport=season.sport, season=season, captain=captain
            )
        start = timezone.make_aware(datetime.datetime(2026, 11, 1, 18, 0))
        matches = []
        for day, (home, away, home_score, away_score) in enumerate(
            [
                ("charlie", "bravo", 1, 1),
                ("alpha", "delta", 1, 0),
                ("bravo", "delta", 2, 1),
            ]
        ):
            matches.append(
                Match.objects.create(
                    season=season,
                    home_team=teams[home],
                    away_team=teams[away],
                    facility=self.facilities[0],
                    starts_at=start + datetime.timedelta(days=day),
                    ends_at=start + datetime.timedelta(days=day, hours=1),
                    home_score=home_score,
                    away_score=away_score,
                )
            )
        self.assertEqual(compute_standings(season)[0]["team"], teams["bravo"])
        self.assertEqual(ensure_leader_first(season, teams["alpha"], matches), 1)
        matches[0].refresh_from_db()
        self.assertEqual((matches[0].home_score, matches[0].away_score), (2, 1))
        self.assertEqual(compute_standings(season)[0]["team"], teams["alpha"])

    def test_ensure_leader_first_skips_a_change_that_lifts_another_team(self):
        season = self.season("Futsal")
        User = get_user_model()
        teams = {}
        for key in ("alpha", "bravo", "charlie"):
            captain = User.objects.create_user(f"{key}9@nyu.edu")
            teams[key] = Team.objects.create(
                name=key.title(), sport=season.sport, season=season, captain=captain
            )
        start = timezone.make_aware(datetime.datetime(2026, 11, 1, 18, 0))
        match = Match.objects.create(
            season=season,
            home_team=teams["charlie"],
            away_team=teams["bravo"],
            facility=self.facilities[0],
            starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
            home_score=1,
            away_score=1,
        )
        # Making Bravo lose would put Charlie above Alpha, so nothing changes.
        self.assertEqual(ensure_leader_first(season, teams["alpha"], [match]), 0)
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (1, 1))

    def test_second_run_creates_nothing(self):
        self.seed()
        before = [snapshot(model) for model in (get_user_model(), Team, Roster, Match)]
        output = self.seed(today="2026-11-20")
        self.assertIn("created 0 teams, 0 roster entries, 0 placeholder", output)
        self.assertIn("0 matches", output)
        after = [snapshot(model) for model in (get_user_model(), Team, Roster, Match)]
        self.assertEqual(after, before)

    def test_existing_team_is_reused_unchanged(self):
        season = self.season("Basketball")
        owner = get_user_model().objects.create_user("owner@nyu.edu")
        team = Team.objects.create(
            name="Delta Basketball", sport=season.sport, season=season, captain=owner
        )
        Roster.objects.create(team=team, player=owner, role=Roster.Role.CAPTAIN)
        self.seed()
        self.assertEqual(list(team.roster.values_list("player", flat=True)), [owner.pk])
        self.assertTrue(Match.objects.filter(home_team=team).exists())

    def test_dry_run_writes_nothing(self):
        output = self.seed("--dry-run")
        self.assertIn("would create 6 teams", output)
        self.assertIn("Dry run: nothing saved.", output)
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Team.objects.exists())
        self.assertFalse(Match.objects.exists())

    def test_sends_no_email_and_makes_no_notifications_or_audit_rows(self):
        audit_rows = AuditLog.objects.count()
        self.seed()
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(AuditLog.objects.count(), audit_rows)

    def test_skips_missing_draft_and_closed_seasons(self):
        data = roster_data()
        data["sports"].append("Curling")
        for team in data["teams"]:
            team["names"]["Curling"] = f"{team['key']} curling"
        self.write(data)
        Season.objects.filter(pk=self.season("Volleyball").pk).update(
            state=SeasonState.DRAFT
        )
        Season.objects.filter(pk=self.season("Futsal").pk).update(
            state=SeasonState.CLOSED
        )
        output = self.seed()
        self.assertIn("Curling: no 2026-fall default season; skipped.", output)
        self.assertIn("Volleyball: Fall 2026 Volleyball is Draft; skipped.", output)
        self.assertIn("Futsal: Fall 2026 Futsal is Closed; skipped.", output)
        self.assertEqual(
            set(Team.objects.values_list("sport__name", flat=True)), {"Basketball"}
        )

    def test_no_facility_means_no_matches(self):
        Facility.objects.update(is_active=False)
        output = self.seed()
        self.assertIn("no active facility", output)
        self.assertEqual(Team.objects.count(), 18)
        self.assertFalse(Match.objects.exists())
