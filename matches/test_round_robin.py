"""Round-robin schedule generation (#214)."""

import datetime
from collections import Counter
from itertools import combinations
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from facilities.models import Facility
from notifications.models import Notification
from teams.models import Division, Season, Sport, Team
from teams.season_rules import SeasonState

from .models import Match
from .round_robin import create_planned_matches, pairings, plan_round_robin

NY = ZoneInfo("America/New_York")
FIRST_DATE = datetime.date(2026, 11, 16)
HOUR = datetime.timedelta(hours=1)
URL = reverse("matches:round_robin")


class PairingsTests(SimpleTestCase):
    def test_too_few_teams_have_no_rounds(self):
        self.assertEqual(pairings([]), [])
        self.assertEqual(pairings(["only"]), [])

    def test_every_pair_meets_once(self):
        for count in range(2, 12):
            with self.subTest(teams=count):
                teams = list(range(count))
                pairs = [pair for round_ in pairings(teams) for pair in round_]
                self.assertEqual(
                    sorted(tuple(sorted(pair)) for pair in pairs),
                    sorted(combinations(teams, 2)),
                )

    def test_a_team_plays_at_most_once_a_round(self):
        for count in range(2, 12):
            with self.subTest(teams=count):
                rounds = pairings(range(count))
                # Even: everyone plays every round. Odd: one team rests.
                self.assertEqual(len(rounds), count - 1 if count % 2 == 0 else count)
                for round_ in rounds:
                    playing = [team for pair in round_ for team in pair]
                    self.assertEqual(len(playing), len(set(playing)))
                    self.assertEqual(len(round_), count // 2)

    def test_home_and_away_are_balanced(self):
        for count in range(2, 12):
            with self.subTest(teams=count):
                balance = Counter()
                for round_ in pairings(range(count)):
                    for home, away in round_:
                        balance[home] += 1
                        balance[away] -= 1
                worst = max(abs(value) for value in balance.values())
                self.assertEqual(worst, 1 if count % 2 == 0 else 0)


class RoundRobinFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.admin = users.create_user(
            username="admin", email="admin@nyu.edu", password="pass12345!"
        )
        assign_role(cls.admin, LEAGUE_ADMIN_ROLE)
        cls.player = users.create_user(
            username="player", email="player@nyu.edu", password="pass12345!"
        )
        cls.soccer = Sport.objects.create(name="Soccer")
        cls.hoops = Sport.objects.create(name="Basketball")
        cls.season = Season.objects.create(
            name="Fall", start_date=datetime.date(2026, 9, 1), state=SeasonState.OPEN
        )
        cls.east = Division.objects.create(season=cls.season, name="East")
        cls.teams = [
            cls.make_team(name, cls.soccer, division)
            for name, division in [
                ("Arches", cls.east),
                ("Bobcats", cls.east),
                ("Torches", cls.east),
                ("Violets", None),
            ]
        ]
        cls.field = Facility.objects.create(name="Pier 40", source=Facility.Source.NYU)
        cls.gym = Facility.objects.create(name="Palladium", source=Facility.Source.NYU)
        cls.closed_gym = Facility.objects.create(
            name="Coles", source=Facility.Source.NYU, is_active=False
        )

    @classmethod
    def make_team(cls, name, sport, division=None, season=None):
        return Team.objects.create(
            name=name,
            sport=sport,
            season=season or cls.season,
            division=division,
            captain=cls.player,
        )

    def plan(self, **overrides):
        values = dict(
            first_date=FIRST_DATE,
            start_time=datetime.time(18, 0),
            match_length=HOUR,
            days_between_rounds=7,
        )
        values.update(overrides)
        return plan_round_robin(self.season, **values)

    def book(self, home, away, facility=None, hour=18, **extra):
        starts_at = datetime.datetime(2026, 11, 16, hour, 0, tzinfo=NY)
        return Match.objects.create(
            season=self.season,
            home_team=home,
            away_team=away,
            facility=facility or self.field,
            starts_at=starts_at,
            ends_at=starts_at + HOUR,
            **extra,
        )

    def post_data(self, **overrides):
        data = {
            "season": self.season.pk,
            "division": "",
            "first_date": "2026-11-16",
            "start_time": "18:00",
            "match_length": "60",
            "days_between_rounds": "7",
        }
        data.update(overrides)
        return data

    def preview(self, **overrides):
        response = self.client.post(URL, self.post_data(**overrides))
        self.assertEqual(response.status_code, 200)
        return response


class PlanTests(RoundRobinFixtures):
    def test_plans_every_pair_by_round(self):
        plan = self.plan()
        self.assertEqual((plan.pair_count, plan.skipped), (6, 0))
        self.assertEqual(len(plan.matches), 6)
        self.assertEqual([round_.number for round_ in plan.rounds], [1, 2, 3])
        self.assertEqual(
            [round_.date for round_ in plan.rounds],
            [FIRST_DATE + datetime.timedelta(days=7 * n) for n in range(3)],
        )
        first = plan.matches[0].match
        self.assertEqual(
            first.starts_at, datetime.datetime(2026, 11, 16, 18, 0, tzinfo=NY)
        )
        self.assertEqual(first.ends_at - first.starts_at, HOUR)
        self.assertFalse(Match.objects.exists())

    def test_matches_in_a_round_never_share_a_facility_and_time(self):
        plan = self.plan(facilities=[self.field])
        for round_ in plan.rounds:
            first, second = (planned.match for planned in round_.matches)
            self.assertEqual(first.facility, self.field)
            # One facility, two matches: the second starts when the first ends.
            self.assertEqual(second.starts_at, first.ends_at)
        both = self.plan(facilities=[self.field, self.gym])
        for round_ in both.rounds:
            first, second = (planned.match for planned in round_.matches)
            self.assertEqual(first.starts_at, second.starts_at)
            self.assertNotEqual(first.facility, second.facility)

    def test_no_facilities_means_any_active_one(self):
        used = {planned.match.facility for planned in self.plan().matches}
        self.assertEqual(used, {self.field, self.gym})

    def test_no_facilities_prefers_the_sports_own(self):
        self.gym.sports.add(self.soccer)
        used = {planned.match.facility for planned in self.plan().matches}
        self.assertEqual(used, {self.gym})

    def test_needs_a_facility(self):
        Facility.objects.update(is_active=False)
        with self.assertRaises(ValueError):
            self.plan()

    def test_skips_pairs_that_already_have_a_match(self):
        a, b, c, d = self.teams
        self.book(b, a)  # either order counts
        self.book(c, d, status=Match.Status.CANCELLED)  # so does a cancelled one
        plan = self.plan()
        self.assertEqual((plan.pair_count, plan.skipped), (6, 2))
        planned = {
            frozenset((p.match.home_team, p.match.away_team)) for p in plan.matches
        }
        self.assertEqual(len(planned), 4)
        self.assertNotIn(frozenset((a, b)), planned)
        self.assertNotIn(frozenset((c, d)), planned)

    def test_matches_of_another_season_do_not_count(self):
        other = Season.objects.create(
            name="Spring", start_date=datetime.date(2027, 1, 1), state=SeasonState.OPEN
        )
        x = self.make_team("X", self.soccer, season=other)
        y = self.make_team("Y", self.soccer, season=other)
        Match.objects.create(
            season=other,
            home_team=x,
            away_team=y,
            facility=self.field,
            starts_at=datetime.datetime(2026, 11, 16, 18, 0, tzinfo=NY),
            ends_at=datetime.datetime(2026, 11, 16, 19, 0, tzinfo=NY),
        )
        self.assertEqual(self.plan().skipped, 0)

    def test_division_limits_the_teams(self):
        plan = self.plan(division=self.east)
        self.assertEqual(plan.pair_count, 3)
        for planned in plan.matches:
            self.assertEqual(planned.match.home_team.division, self.east)
            self.assertEqual(planned.match.away_team.division, self.east)

    def test_teams_only_meet_their_own_sport(self):
        self.make_team("Hoopers", self.hoops)
        self.make_team("Dunkers", self.hoops)
        plan = self.plan()
        self.assertEqual(plan.pair_count, 7)
        for planned in plan.matches:
            self.assertEqual(
                planned.match.home_team.sport, planned.match.away_team.sport
            )

    def test_overlap_with_an_existing_match_is_a_warning(self):
        other = Season.objects.create(
            name="Spring", start_date=datetime.date(2027, 1, 1), state=SeasonState.OPEN
        )
        x = self.make_team("X", self.soccer, season=other)
        y = self.make_team("Y", self.soccer, season=other)
        booked = Match.objects.create(
            season=other,
            home_team=x,
            away_team=y,
            facility=self.field,
            starts_at=datetime.datetime(2026, 11, 16, 18, 30, tzinfo=NY),
            ends_at=datetime.datetime(2026, 11, 16, 19, 30, tzinfo=NY),
        )
        plan = self.plan(facilities=[self.field])
        self.assertEqual(plan.overlap_count, 2)  # the 6 PM and the 7 PM slot
        self.assertEqual(plan.matches[0].overlaps, [booked])
        # A free facility is used before an overlapping one.
        self.assertEqual(self.plan(facilities=[self.field, self.gym]).overlap_count, 1)
        booked.cancel()
        self.assertEqual(self.plan(facilities=[self.field]).overlap_count, 0)

    def test_token_changes_with_the_plan(self):
        token = self.plan().token
        self.assertEqual(token, self.plan().token)
        self.assertNotEqual(token, self.plan(days_between_rounds=3).token)
        self.book(*self.teams[:2])
        self.assertNotEqual(token, self.plan().token)


class CreateTests(RoundRobinFixtures):
    def test_creates_every_match_and_notifies(self):
        created = create_planned_matches(self.plan(), created_by=self.admin)
        self.assertEqual(len(created), 6)
        self.assertEqual(Match.objects.filter(created_by=self.admin).count(), 6)
        self.assertTrue(Notification.objects.exists())
        self.assertEqual(self.plan().matches, [])

    def test_a_failure_saves_nothing_and_names_the_match(self):
        plan = self.plan()
        bad = plan.matches[3].match
        bad.away_team = self.make_team("Hoopers", self.hoops)
        with self.assertRaises(ValidationError) as caught:
            create_planned_matches(plan)
        message = caught.exception.messages[0]
        self.assertIn(str(bad), message)
        self.assertIn("same sport", message)
        self.assertFalse(Match.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_season_must_allow_scheduling(self):
        plan = self.plan()
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        self.season.refresh_from_db()
        with self.assertRaises(ValidationError):
            create_planned_matches(plan)
        self.assertFalse(Match.objects.exists())

    def test_inactive_facility_is_refused(self):
        plan = self.plan(facilities=[self.closed_gym])
        with self.assertRaises(ValidationError):
            create_planned_matches(plan)
        self.assertFalse(Match.objects.exists())


class RoundRobinViewTests(RoundRobinFixtures):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(URL).status_code, 302)
        self.assertEqual(self.client.post(URL, self.post_data()).status_code, 302)

    def test_other_users_get_403(self):
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.post(URL, self.post_data()).status_code, 403)
        self.assertFalse(Match.objects.exists())

    def test_manage_page_links_here_with_one_primary_action(self):
        response = self.client.get(
            reverse("matches:manage"), {"season": self.season.pk}
        )
        self.assertContains(response, f"{URL}?season={self.season.pk}")
        self.assertContains(response, "btn btn-primary", count=1)

    def test_get_shows_the_form_with_the_season_chosen(self):
        response = self.client.get(URL, {"season": self.season.pk})
        self.assertContains(response, "Preview schedule")
        self.assertEqual(
            response.context["form"]["season"].value(), str(self.season.pk)
        )
        self.assertIsNone(response.context["plan"])
        self.assertNotContains(response, self.closed_gym.name)

    def test_preview_lists_the_plan_and_saves_nothing(self):
        self.book(*self.teams[:2])
        Match.objects.all().update(facility=self.gym)
        Notification.objects.all().delete()
        response = self.preview(facilities=[self.field.pk])
        plan = response.context["plan"]
        self.assertEqual(len(plan.matches), 5)
        self.assertContains(response, "5 to create · 1 skipped as already scheduled")
        self.assertContains(response, "Create 5 matches")
        self.assertContains(response, "Round ", count=3)
        self.assertContains(response, "btn btn-primary", count=1)
        self.assertNotContains(response, "alert-warning")
        self.assertEqual(Match.objects.count(), 1)
        self.assertFalse(Notification.objects.exists())

    def test_preview_warns_about_overlaps(self):
        self.book(*self.teams[:2])
        response = self.preview(facilities=[self.field.pk])
        self.assertContains(response, "alert alert-warning text-body")
        self.assertContains(response, "1 planned match overlaps an existing booking")
        self.assertContains(response, "Create 5 matches anyway")

    def test_confirm_creates_the_matches(self):
        token = self.preview().context["plan"].token
        response = self.client.post(URL, self.post_data(confirm=token), follow=True)
        self.assertRedirects(
            response, f"{reverse('matches:manage')}?season={self.season.pk}"
        )
        self.assertContains(response, "Scheduled 6 matches in Fall.")
        self.assertEqual(Match.objects.filter(created_by=self.admin).count(), 6)
        pairs = {
            frozenset(pair)
            for pair in Match.objects.values_list("home_team_id", "away_team_id")
        }
        self.assertEqual(len(pairs), 6)

    def test_confirm_with_overlaps_creates_them_like_schedule_anyway(self):
        self.book(*self.teams[:2])
        data = self.post_data(facilities=[self.field.pk])
        token = self.client.post(URL, data).context["plan"].token
        self.client.post(URL, {**data, "confirm": token})
        self.assertEqual(Match.objects.count(), 6)

    def test_confirm_ignores_a_stale_or_forged_token(self):
        token = self.preview().context["plan"].token
        for data in (
            self.post_data(confirm="forged"),
            self.post_data(confirm=token, days_between_rounds="3"),
        ):
            response = self.client.post(URL, data)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "The schedule changed since the preview")
            self.assertFalse(Match.objects.exists())

    def test_confirm_plans_again_from_the_form(self):
        token = self.preview().context["plan"].token
        # Posted teams are not form fields, so they change nothing.
        data = self.post_data(confirm=token, home_team=self.teams[0].pk, matches="1")
        self.client.post(URL, data)
        self.assertEqual(Match.objects.count(), 6)

    def test_second_run_has_nothing_to_create(self):
        token = self.preview().context["plan"].token
        self.client.post(URL, self.post_data(confirm=token))
        response = self.preview()
        self.assertContains(response, "Nothing to create")
        self.assertNotContains(response, 'name="confirm"')
        self.client.post(URL, self.post_data(confirm=token))
        self.assertEqual(Match.objects.count(), 6)

    def test_failure_on_confirm_rolls_back_and_names_the_match(self):
        token = self.preview().context["plan"].token
        error = ValidationError(
            {"away_team": "Both teams have to play the same sport."}
        )
        calls = []

        def fail_on_third(match, *args, **kwargs):
            calls.append(match)
            if len(calls) == 3:
                raise error

        with mock.patch.object(Match, "full_clean", autospec=True) as full_clean:
            full_clean.side_effect = fail_on_third
            response = self.client.post(URL, self.post_data(confirm=token))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{calls[2]} on Nov ")
        self.assertContains(response, "No matches were created.")
        self.assertFalse(Match.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_division_limits_the_preview(self):
        response = self.preview(division=self.east.pk)
        self.assertEqual(len(response.context["plan"].matches), 3)
        self.assertNotContains(response, "Violets")

    def test_division_must_belong_to_the_season(self):
        other = Season.objects.create(
            name="Spring", start_date=datetime.date(2027, 1, 1), state=SeasonState.OPEN
        )
        west = Division.objects.create(season=other, name="West")
        response = self.preview(division=west.pk)
        self.assertIsNone(response.context["plan"])
        self.assertIn("division", response.context["form"].errors)

    def test_season_must_allow_scheduling(self):
        token = self.preview().context["plan"].token
        for state in (SeasonState.DRAFT, SeasonState.CLOSED):
            Season.objects.filter(pk=self.season.pk).update(state=state)
            response = self.client.post(URL, self.post_data(confirm=token))
            self.assertContains(
                response,
                "Matches can only be scheduled while a season is open or active.",
            )
            self.assertFalse(Match.objects.exists())

    def test_fewer_than_two_teams_gets_a_friendly_message(self):
        Team.objects.exclude(pk=self.teams[0].pk).update(season=None, division=None)
        response = self.preview()
        self.assertIsNone(response.context["plan"])
        self.assertContains(response, "needs at least 2 teams")
        self.assertContains(response, "Fall doesn&#x27;t have them yet.")

    def test_inactive_facility_cannot_be_chosen(self):
        response = self.preview(facilities=[self.closed_gym.pk])
        self.assertIsNone(response.context["plan"])
        self.assertIn("facilities", response.context["form"].errors)

    def test_no_active_facility_gets_a_message(self):
        Facility.objects.update(is_active=False)
        response = self.preview()
        self.assertContains(response, "Add an active facility")

    def test_bad_numbers_are_form_errors(self):
        response = self.preview(match_length="0", days_between_rounds="0")
        errors = response.context["form"].errors
        self.assertIn("match_length", errors)
        self.assertIn("days_between_rounds", errors)
