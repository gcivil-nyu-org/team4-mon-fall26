import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
from facilities.models import Facility
from teams.models import Season, Sport, Team
from teams.season_rules import SeasonState

from .models import Match

NY = ZoneInfo("America/New_York")


def make_user(username, admin=False):
    user = get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )
    if admin:
        assign_role(user, LEAGUE_ADMIN_ROLE)
    return user


def at(day, hour):
    return datetime.datetime(2026, 11, day, hour, 0, tzinfo=NY)


class MatchFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin", admin=True)
        cls.player = make_user("player")
        cls.soccer = Sport.objects.create(name="Soccer")
        cls.hoops = Sport.objects.create(name="Basketball")
        cls.season = Season.objects.create(
            name="Fall", start_date=datetime.date(2026, 9, 1), state=SeasonState.OPEN
        )
        cls.other_season = Season.objects.create(
            name="Spring", start_date=datetime.date(2027, 1, 1), state=SeasonState.OPEN
        )
        cls.home = cls.make_team("Violets", cls.soccer, cls.season)
        cls.away = cls.make_team("Bobcats", cls.soccer, cls.season)
        cls.hoops_team = cls.make_team("Hoopers", cls.hoops, cls.season)
        cls.outsider = cls.make_team("Outsiders", cls.soccer, cls.other_season)
        cls.field = Facility.objects.create(name="Pier 40", source=Facility.Source.NYU)

    @classmethod
    def make_team(cls, name, sport, season):
        return Team.objects.create(
            name=name, sport=sport, season=season, captain=cls.player
        )

    def build(self, **overrides):
        values = dict(
            season=self.season,
            home_team=self.home,
            away_team=self.away,
            facility=self.field,
            starts_at=at(10, 18),
            ends_at=at(10, 20),
        )
        values.update(overrides)
        return Match(**values)

    def post_data(self, **overrides):
        data = {
            "home_team": self.home.pk,
            "away_team": self.away.pk,
            "facility": self.field.pk,
            "starts_at": "2026-11-10T18:00",
            "ends_at": "2026-11-10T20:00",
        }
        data.update(overrides)
        return data


class MatchModelTests(MatchFixtures):
    def test_valid_match(self):
        match = self.build()
        match.full_clean()
        match.save()
        self.assertEqual(str(match), "Violets vs Bobcats")
        self.assertEqual(match.status, Match.Status.SCHEDULED)
        self.assertIn(match, Match.objects.scheduled())

    def test_end_must_be_after_start(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(ends_at=at(10, 18)).full_clean()
        self.assertIn("ends_at", ctx.exception.message_dict)

    def test_team_cannot_play_itself(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(away_team=self.home).full_clean()
        self.assertIn("away_team", ctx.exception.message_dict)

    def test_teams_must_be_in_the_season(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(away_team=self.outsider).full_clean()
        self.assertEqual(
            ctx.exception.message_dict["away_team"], ["Choose a team from this season."]
        )

    def test_teams_must_play_the_same_sport(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(away_team=self.hoops_team).full_clean()
        self.assertIn("same sport", ctx.exception.message_dict["away_team"][0])

    def test_database_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.build(away_team=self.home).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.build(ends_at=at(10, 17)).save()

    def test_validate_schedulable_by_season_state(self):
        for state, allowed in [
            (SeasonState.DRAFT, False),
            (SeasonState.OPEN, True),
            (SeasonState.ACTIVE, True),
            (SeasonState.CLOSED, False),
        ]:
            with self.subTest(state=state):
                self.season.state = state
                match = self.build()
                if allowed:
                    match.validate_schedulable()
                else:
                    with self.assertRaises(ValidationError):
                        match.validate_schedulable()

    def test_inactive_facility(self):
        self.field.is_active = False
        self.field.save()
        with self.assertRaises(ValidationError):
            self.build().validate_schedulable()
        self.build().validate_schedulable(check_facility=False)

    def test_cancel(self):
        match = self.build()
        match.save()
        match.cancel()
        match.refresh_from_db()
        self.assertTrue(match.is_cancelled)
        self.assertNotIn(match, Match.objects.scheduled())

    def test_facility_with_matches_cannot_be_deleted(self):
        self.build().save()
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            self.field.delete()


class MatchPermissionTests(MatchFixtures):
    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("matches:manage"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_non_admin_gets_403_everywhere(self):
        match = self.build()
        match.save()
        self.client.force_login(self.player)
        for method, url in [
            ("get", reverse("matches:manage")),
            ("get", reverse("matches:create")),
            ("post", reverse("matches:create") + f"?season={self.season.pk}"),
            ("get", reverse("matches:edit", args=[match.pk])),
            ("post", reverse("matches:cancel", args=[match.pk])),
        ]:
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403)
        match.refresh_from_db()
        self.assertFalse(match.is_cancelled)

    def test_cancel_requires_post(self):
        match = self.build()
        match.save()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("matches:cancel", args=[match.pk]))
        self.assertEqual(response.status_code, 405)


class MatchViewTests(MatchFixtures):
    def setUp(self):
        self.client.force_login(self.admin)

    def create_url(self, season=None):
        season = season or self.season
        return reverse("matches:create") + f"?season={season.pk}"

    def test_list_and_filter(self):
        self.build().save()
        Match.objects.create(
            season=self.other_season,
            home_team=self.outsider,
            away_team=self.make_team("Others", self.soccer, self.other_season),
            facility=self.field,
            starts_at=at(11, 18),
            ends_at=at(11, 19),
        )
        response = self.client.get(reverse("matches:manage"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["matches"]), 2)
        self.assertContains(response, "Schedule a match")
        response = self.client.get(
            reverse("matches:manage") + f"?season={self.season.pk}"
        )
        self.assertEqual(
            list(response.context["matches"]), list(self.season.matches.all())
        )

    def test_empty_list_without_schedulable_season(self):
        Season.objects.update(state=SeasonState.DRAFT)
        response = self.client.get(reverse("matches:manage"))
        self.assertContains(response, "Open a season first")
        self.assertNotContains(response, "Schedule a match</a>")

    def test_create_without_season_shows_season_picker(self):
        Season.objects.create(name="Draft one", start_date=datetime.date(2027, 5, 1))
        response = self.client.get(reverse("matches:create"))
        self.assertTemplateUsed(response, "matches/choose_season.html")
        self.assertEqual(
            {s.name for s in response.context["seasons"]}, {"Fall", "Spring"}
        )

    def test_create_rejects_draft_or_closed_season(self):
        for state in (SeasonState.DRAFT, SeasonState.CLOSED):
            with self.subTest(state=state):
                Season.objects.filter(pk=self.season.pk).update(state=state)
                response = self.client.get(self.create_url())
                self.assertEqual(response.status_code, 404)

    def test_form_only_offers_season_teams_and_active_facilities(self):
        Facility.objects.create(
            name="Closed gym", source=Facility.Source.NYU, is_active=False
        )
        response = self.client.get(self.create_url())
        form = response.context["form"]
        self.assertEqual(
            set(form.fields["home_team"].queryset),
            {self.home, self.away, self.hoops_team},
        )
        self.assertEqual(list(form.fields["facility"].queryset), [self.field])

    def test_schedule_match(self):
        response = self.client.post(self.create_url(), self.post_data())
        self.assertRedirects(
            response, reverse("matches:manage") + f"?season={self.season.pk}"
        )
        match = Match.objects.get()
        self.assertEqual(match.season, self.season)
        self.assertEqual(match.created_by, self.admin)
        # Entered as New York time.
        self.assertEqual(match.starts_at, at(10, 18))
        self.assertEqual(match.starts_at.astimezone(datetime.timezone.utc).hour, 23)

    def test_schedule_invalid_shows_errors(self):
        for data, field in [
            (self.post_data(away_team=self.home.pk), "away_team"),
            (self.post_data(away_team=self.hoops_team.pk), "away_team"),
            (self.post_data(away_team=self.outsider.pk), "away_team"),
            (self.post_data(ends_at="2026-11-10T17:00"), "ends_at"),
        ]:
            with self.subTest(data=data):
                response = self.client.post(self.create_url(), data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors.get(field))
        self.assertFalse(Match.objects.exists())

    def test_edit_match(self):
        match = self.build()
        match.save()
        response = self.client.post(
            reverse("matches:edit", args=[match.pk]),
            self.post_data(starts_at="2026-11-12T09:00", ends_at="2026-11-12T10:30"),
        )
        self.assertEqual(response.status_code, 302)
        match.refresh_from_db()
        self.assertEqual(match.starts_at, at(12, 9))
        self.assertIsNone(match.created_by)

    def test_edit_keeps_deactivated_facility_but_blocks_switching_to_one(self):
        match = self.build()
        match.save()
        self.field.is_active = False
        self.field.save()
        url = reverse("matches:edit", args=[match.pk])
        response = self.client.post(url, self.post_data(ends_at="2026-11-10T21:00"))
        self.assertEqual(response.status_code, 302)

        other = Facility.objects.create(
            name="Old gym", source=Facility.Source.NYU, is_active=False
        )
        response = self.client.post(url, self.post_data(facility=other.pk))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_edit_blocked_once_season_closed(self):
        match = self.build()
        match.save()
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        response = self.client.post(
            reverse("matches:edit", args=[match.pk]), self.post_data()
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "open or active", " ".join(response.context["form"].non_field_errors())
        )

    def test_cancel_and_cancelled_match_is_read_only(self):
        match = self.build()
        match.save()
        response = self.client.post(reverse("matches:cancel", args=[match.pk]))
        self.assertEqual(response.status_code, 302)
        match.refresh_from_db()
        self.assertTrue(match.is_cancelled)

        response = self.client.post(reverse("matches:cancel", args=[match.pk]))
        self.assertEqual(response.status_code, 302)

        response = self.client.get(reverse("matches:edit", args=[match.pk]))
        self.assertRedirects(response, reverse("matches:manage"))

    def test_league_setup_hub_counts_upcoming_matches(self):
        self.build(
            starts_at=timezone.now() + datetime.timedelta(days=1),
            ends_at=timezone.now() + datetime.timedelta(days=1, hours=1),
        ).save()
        self.build(starts_at=at(1, 9), ends_at=at(1, 10)).save()
        response = self.client.get(reverse("teams:league_setup"))
        self.assertEqual(response.context["counts"]["upcoming_matches"], 1)
        self.assertContains(response, reverse("matches:manage"))
