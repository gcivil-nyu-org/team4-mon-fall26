import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from accounts.roles import LEAGUE_ADMIN_ROLE, SCOREKEEPER_ROLE, assign_role
from facilities.models import Facility
from teams.models import Season, Sport, Team
from teams.season_rules import SeasonState

from .forms import OVERLAP_CONFIRMATION_FIELD as CONFIRM
from .forms import MatchForm
from .models import Match

NY = ZoneInfo("America/New_York")
HALF_HOUR = datetime.timedelta(minutes=30)


def make_user(username, admin=False, scorekeeper=False):
    user = get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )
    if admin:
        assign_role(user, LEAGUE_ADMIN_ROLE)
    if scorekeeper:
        assign_role(user, SCOREKEEPER_ROLE)
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

    def test_cancel(self):
        match = self.build()
        match.save()
        match.cancel()
        match.refresh_from_db()
        self.assertTrue(match.is_cancelled)
        self.assertNotIn(match, Match.objects.scheduled())

    def test_facility_and_teams_with_matches_cannot_be_deleted(self):
        self.build().save()
        for protected in (self.field, self.home, self.away):
            with self.subTest(protected=protected):
                with self.assertRaises(ProtectedError):
                    protected.delete()


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

    def test_edit_can_keep_a_deactivated_facility(self):
        match = self.build()
        match.save()
        Facility.objects.filter(pk=self.field.pk).update(is_active=False)
        response = self.client.post(
            reverse("matches:edit", args=[match.pk]),
            self.post_data(ends_at="2026-11-10T21:00"),
        )
        self.assertEqual(response.status_code, 302)

    def test_edit_can_move_off_a_deactivated_facility(self):
        match = self.build()
        match.save()
        Facility.objects.filter(pk=self.field.pk).update(is_active=False)
        other = Facility.objects.create(name="Coles", source=Facility.Source.NYU)
        response = self.client.post(
            reverse("matches:edit", args=[match.pk]),
            self.post_data(facility=other.pk),
        )
        self.assertEqual(response.status_code, 302)
        match.refresh_from_db()
        self.assertEqual(match.facility, other)

    def test_cannot_switch_to_an_inactive_facility(self):
        match = self.build()
        match.save()
        other = Facility.objects.create(
            name="Old gym", source=Facility.Source.NYU, is_active=False
        )
        response = self.client.post(
            reverse("matches:edit", args=[match.pk]),
            self.post_data(facility=other.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("valid choice", response.context["form"].errors["facility"][0])
        match.refresh_from_db()
        self.assertEqual(match.facility, self.field)

    def test_form_rejects_inactive_facility_even_if_offered(self):
        """Guards the form's own check, separately from the choices it offers."""
        other = Facility.objects.create(
            name="Old gym", source=Facility.Source.NYU, is_active=False
        )
        form = MatchForm(self.post_data(facility=other.pk), season=self.season)
        form.fields["facility"].queryset = Facility.objects.all()
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["facility"], ["This facility isn't available."])

    def test_closed_season_matches_are_read_only(self):
        match = self.build()
        match.save()
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        response = self.client.get(reverse("matches:manage"))
        self.assertNotContains(response, reverse("matches:cancel", args=[match.pk]))
        self.assertNotContains(response, reverse("matches:edit", args=[match.pk]))
        self.client.post(reverse("matches:cancel", args=[match.pk]))
        match.refresh_from_db()
        self.assertFalse(match.is_cancelled)

    def test_schedule_link_ignores_a_closed_season_filter(self):
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        response = self.client.get(
            reverse("matches:manage") + f"?season={self.season.pk}"
        )
        self.assertContains(response, f'href="{reverse("matches:create")}"')
        self.assertNotContains(
            response, f'{reverse("matches:create")}?season={self.season.pk}'
        )

    def test_non_ascii_digit_in_season_filter_is_ignored(self):
        for url in (reverse("matches:manage"), reverse("matches:create")):
            with self.subTest(url=url):
                response = self.client.get(url, {"season": "²"})
                self.assertEqual(response.status_code, 200)

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
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        response = self.client.get(reverse("teams:league_setup"))
        self.assertEqual(response.context["counts"]["upcoming_matches"], 0)
        self.assertContains(response, reverse("matches:manage"))


class ScorekeeperFixtures(MatchFixtures):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.keeper = make_user("keeper", scorekeeper=True)
        cls.other_keeper = make_user("otherkeeper", scorekeeper=True)
        cls.superuser = get_user_model().objects.create_superuser(
            username="root", email="root@nyu.edu", password="pass12345!"
        )

    def assign(self, keeper=None, **overrides):
        match = self.build(scorekeeper=keeper or self.keeper, **overrides)
        match.save()
        return match

    def edit_url(self, match):
        return reverse("matches:edit", args=[match.pk])

    def remove_role(self, user):
        user.groups.remove(Group.objects.get(name=SCOREKEEPER_ROLE))


class ScorekeeperRoleTests(TestCase):
    def test_migration_creates_the_role(self):
        self.assertTrue(Group.objects.filter(name=SCOREKEEPER_ROLE).exists())


class ScorekeeperModelTests(ScorekeeperFixtures):
    def test_scorekeeper_is_optional(self):
        match = self.build()
        match.full_clean()
        self.assertIsNone(match.scorekeeper)

    def test_scorekeeper_role_can_be_assigned(self):
        self.build(scorekeeper=self.keeper).full_clean()

    def test_users_without_the_role_cannot_be_assigned(self):
        for user in (self.player, self.admin, self.superuser):
            with self.subTest(user=user.username):
                with self.assertRaises(ValidationError) as caught:
                    self.build(scorekeeper=user).full_clean()
                self.assertIn("scorekeeper", caught.exception.message_dict)

    def test_inactive_scorekeeper_cannot_be_assigned(self):
        get_user_model().objects.filter(pk=self.keeper.pk).update(is_active=False)
        with self.assertRaises(ValidationError) as caught:
            self.build(scorekeeper=self.keeper).full_clean()
        self.assertIn("scorekeeper", caught.exception.message_dict)

    def test_losing_the_role_keeps_the_assignment_and_allows_other_edits(self):
        match = self.assign()
        self.remove_role(self.keeper)
        match.refresh_from_db()
        self.assertEqual(match.scorekeeper, self.keeper)
        match.ends_at = at(10, 21)
        match.full_clean()

    def test_stale_scorekeeper_cannot_be_put_on_another_match(self):
        match = self.assign()
        self.remove_role(self.keeper)
        match.scorekeeper = None
        match.save()
        match.scorekeeper = self.keeper
        with self.assertRaises(ValidationError) as caught:
            match.full_clean()
        self.assertIn("scorekeeper", caught.exception.message_dict)

    def test_deleting_the_scorekeeper_keeps_the_match(self):
        match = self.assign()
        self.keeper.delete()
        match.refresh_from_db()
        self.assertIsNone(match.scorekeeper)
        self.assertFalse(match.is_cancelled)


class ScorekeeperFormTests(ScorekeeperFixtures):
    def choices(self, match=None):
        form = MatchForm(instance=match, season=self.season)
        return set(form.fields["scorekeeper"].queryset)

    def test_only_active_scorekeepers_are_offered(self):
        get_user_model().objects.filter(pk=self.other_keeper.pk).update(is_active=False)
        self.assertEqual(self.choices(), {self.keeper})

    def test_scorekeeper_with_extra_roles_is_listed_once(self):
        # Offering the current scorekeeper joins every group they're in.
        assign_role(self.keeper, LEAGUE_ADMIN_ROLE)
        form = MatchForm(instance=self.assign(), season=self.season)
        pks = [user.pk for user in form.fields["scorekeeper"].queryset]
        self.assertEqual(pks.count(self.keeper.pk), 1)

    def test_stale_scorekeeper_stays_selectable_on_their_own_match_only(self):
        match = self.assign()
        self.remove_role(self.keeper)
        self.assertEqual(self.choices(match), {self.keeper, self.other_keeper})
        self.assertEqual(self.choices(), {self.other_keeper})

    def test_form_rejects_a_user_without_the_role(self):
        form = MatchForm(self.post_data(scorekeeper=self.player.pk), season=self.season)
        self.assertFalse(form.is_valid())
        self.assertIn("scorekeeper", form.errors)


class ScorekeeperAssignmentTests(ScorekeeperFixtures):
    def setUp(self):
        self.client.force_login(self.admin)

    def stored_scorekeeper(self, match):
        match.refresh_from_db()
        return match.scorekeeper

    def test_assign_when_scheduling(self):
        url = reverse("matches:create") + f"?season={self.season.pk}"
        self.client.post(url, self.post_data(scorekeeper=self.keeper.pk))
        self.assertEqual(Match.objects.get().scorekeeper, self.keeper)

    def test_scheduling_without_a_scorekeeper_still_works(self):
        url = reverse("matches:create") + f"?season={self.season.pk}"
        self.client.post(url, self.post_data())
        self.assertIsNone(Match.objects.get().scorekeeper)

    def test_admin_can_assign_change_and_clear(self):
        match = self.build()
        match.save()
        for value, expected in [
            (self.keeper.pk, self.keeper),
            (self.other_keeper.pk, self.other_keeper),
            ("", None),
        ]:
            with self.subTest(value=value):
                response = self.client.post(
                    self.edit_url(match), self.post_data(scorekeeper=value)
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.stored_scorekeeper(match), expected)

    def test_superuser_can_assign(self):
        match = self.build()
        match.save()
        self.client.force_login(self.superuser)
        self.client.post(
            self.edit_url(match), self.post_data(scorekeeper=self.keeper.pk)
        )
        self.assertEqual(self.stored_scorekeeper(match), self.keeper)

    def test_posting_a_user_without_the_role_changes_nothing(self):
        match = self.assign()
        response = self.client.post(
            self.edit_url(match), self.post_data(scorekeeper=self.player.pk)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("scorekeeper", response.context["form"].errors)
        self.assertEqual(self.stored_scorekeeper(match), self.keeper)

    def test_rescheduling_keeps_a_stale_scorekeeper(self):
        match = self.assign()
        self.remove_role(self.keeper)
        response = self.client.post(
            self.edit_url(match),
            self.post_data(scorekeeper=self.keeper.pk, ends_at="2026-11-10T21:00"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.stored_scorekeeper(match), self.keeper)
        self.assertEqual(match.ends_at, at(10, 21))

    def test_cancelled_match_is_read_only(self):
        match = self.assign()
        match.cancel()
        response = self.client.post(
            self.edit_url(match), self.post_data(scorekeeper=self.other_keeper.pk)
        )
        self.assertRedirects(response, reverse("matches:manage"))
        self.assertEqual(self.stored_scorekeeper(match), self.keeper)

    def test_closed_season_is_read_only(self):
        match = self.assign()
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        response = self.client.post(
            self.edit_url(match), self.post_data(scorekeeper=self.other_keeper.pk)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored_scorekeeper(match), self.keeper)

    def test_non_admins_cannot_assign(self):
        match = self.build()
        match.save()
        for user in (self.player, self.keeper):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.post(
                    self.edit_url(match), self.post_data(scorekeeper=self.keeper.pk)
                )
                self.assertEqual(response.status_code, 403)
                self.assertIsNone(self.stored_scorekeeper(match))

    def test_anonymous_cannot_assign(self):
        match = self.build()
        match.save()
        self.client.logout()
        response = self.client.post(
            self.edit_url(match), self.post_data(scorekeeper=self.keeper.pk)
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertIsNone(self.stored_scorekeeper(match))

    def test_manage_list_shows_the_scorekeeper_or_unassigned(self):
        self.keeper.first_name, self.keeper.last_name = "Kim", "Park"
        self.keeper.save()
        self.assign()
        self.build(starts_at=at(11, 18), ends_at=at(11, 20)).save()
        response = self.client.get(reverse("matches:manage"))
        self.assertContains(response, "Kim Park")
        self.assertContains(response, "Unassigned")
        self.assertNotContains(response, "Needs reassigning")

    def test_manage_list_flags_a_stale_scorekeeper_on_live_matches_only(self):
        match = self.assign()
        self.remove_role(self.keeper)
        response = self.client.get(reverse("matches:manage"))
        self.assertContains(response, "Needs reassigning")
        match.cancel()
        response = self.client.get(reverse("matches:manage"))
        self.assertNotContains(response, "Needs reassigning")


class MyMatchesTests(ScorekeeperFixtures):
    url = reverse_lazy("matches:mine")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_everyone_without_the_role_gets_403(self):
        for user in (self.player, self.admin, self.superuser):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_losing_the_role_removes_access(self):
        self.assign()
        self.remove_role(self.keeper)
        self.client.force_login(self.keeper)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_lists_only_the_scorekeepers_own_matches(self):
        mine = self.assign()
        self.assign(self.other_keeper, starts_at=at(11, 18), ends_at=at(11, 20))
        self.build(starts_at=at(12, 18), ends_at=at(12, 20)).save()
        self.client.force_login(self.keeper)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        groups = response.context["groups"]
        self.assertEqual(sum(groups.values(), []), [mine])

    def test_cancelled_match_stays_listed_and_is_labelled(self):
        self.assign().cancel()
        self.client.force_login(self.keeper)
        self.assertContains(self.client.get(self.url), "Cancelled")

    def test_empty_state(self):
        self.client.force_login(self.keeper)
        self.assertContains(self.client.get(self.url), "No upcoming matches")

    def test_nav_link_only_for_scorekeepers(self):
        link = f'href="{self.url}"'
        self.client.force_login(self.keeper)
        self.assertContains(self.client.get(reverse("core:home")), link)
        for user in (self.player, self.admin, self.superuser):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertNotContains(self.client.get(reverse("core:home")), link)


class OverlappingHelperTests(MatchFixtures):
    def setUp(self):
        self.existing = self.build()
        self.existing.save()

    def overlapping(self, starts_at, ends_at, facility=None):
        return list(
            Match.objects.overlapping(facility or self.field, starts_at, ends_at)
        )

    def test_windows_against_a_six_to_eight_match(self):
        for name, starts_at, ends_at, overlaps in [
            ("ends when it starts", at(10, 16), at(10, 18), False),
            ("starts when it ends", at(10, 20), at(10, 22), False),
            ("well before", at(10, 9), at(10, 10), False),
            ("well after", at(10, 21), at(10, 22), False),
            ("another day", at(11, 18), at(11, 20), False),
            ("same window", at(10, 18), at(10, 20), True),
            ("runs into it", at(10, 17), at(10, 19), True),
            ("runs past its end", at(10, 19), at(10, 21), True),
            ("inside it", at(10, 18) + HALF_HOUR, at(10, 19), True),
            ("around it", at(10, 17), at(10, 21), True),
        ]:
            with self.subTest(name):
                self.assertEqual(
                    self.overlapping(starts_at, ends_at),
                    [self.existing] if overlaps else [],
                )

    def test_ignores_other_facilities(self):
        other = Facility.objects.create(name="Paulson", source=Facility.Source.NYU)
        self.assertEqual(self.overlapping(at(10, 18), at(10, 20), other), [])

    def test_ignores_cancelled_matches(self):
        self.existing.cancel()
        self.assertEqual(self.overlapping(at(10, 18), at(10, 20)), [])

    def test_counts_matches_from_other_seasons(self):
        self.existing.delete()
        other_season = self.build(
            season=self.other_season,
            home_team=self.outsider,
            away_team=self.make_team("Ravens", self.soccer, self.other_season),
        )
        other_season.save()
        self.assertEqual(self.overlapping(at(10, 18), at(10, 20)), [other_season])


class OverlapWarningTests(MatchFixtures):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hawks = cls.make_team("Hawks", cls.soccer, cls.season)
        cls.owls = cls.make_team("Owls", cls.soccer, cls.season)
        cls.second_field = Facility.objects.create(
            name="Paulson", source=Facility.Source.NYU
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("matches:create") + f"?season={self.season.pk}"
        self.conflict = self.build(home_team=self.hawks, away_team=self.owls)
        self.conflict.save()

    def warn(self, url=None, **overrides):
        """Submit without confirming, check nothing was saved, return the token."""
        before = Match.objects.count()
        response = self.client.post(url or self.url, self.post_data(**overrides))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].overlaps)
        self.assertEqual(Match.objects.count(), before)
        return response.context["form"].overlap_token

    def confirm(self, token, url=None, **overrides):
        data = self.post_data(**overrides)
        return self.client.post(url or self.url, {**data, CONFIRM: token})

    def test_warning_lists_the_conflict_and_asks_for_confirmation(self):
        response = self.client.post(self.url, self.post_data())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Match.objects.count(), 1)
        form = response.context["form"]
        self.assertEqual(form.overlaps, [self.conflict])
        self.assertFalse(form.errors)
        self.assertContains(response, "Pier 40 already has 1 match at this time")
        self.assertContains(response, "Hawks vs Owls")
        self.assertContains(response, "Tue Nov 10, 6:00 PM – 8:00 PM")
        self.assertContains(response, "Schedule anyway")
        self.assertContains(response, f'name="{CONFIRM}"')
        self.assertContains(response, f'value="{form.overlap_token}"')
        self.assertNotContains(response, "alert-danger")

    def test_warning_lists_every_conflict(self):
        later = self.build(
            home_team=self.hawks,
            away_team=self.owls,
            starts_at=at(10, 19),
            ends_at=at(10, 21),
        )
        later.save()
        response = self.client.post(
            self.url, self.post_data(ends_at="2026-11-10T21:00")
        )
        self.assertEqual(response.context["form"].overlaps, [self.conflict, later])
        self.assertContains(response, "Pier 40 already has 2 matches at this time")

    def test_confirming_saves_the_match(self):
        response = self.confirm(self.warn())
        self.assertEqual(response.status_code, 302)
        saved = Match.objects.exclude(pk=self.conflict.pk).get()
        self.assertEqual(saved.home_team, self.home)
        self.assertEqual(saved.created_by, self.admin)
        self.assertEqual(saved.starts_at, at(10, 18))

    def test_no_warning_when_matches_only_touch(self):
        for start, end in [
            ("2026-11-10T20:00", "2026-11-10T21:00"),
            ("2026-11-10T17:00", "2026-11-10T18:00"),
        ]:
            with self.subTest(start=start):
                response = self.client.post(
                    self.url, self.post_data(starts_at=start, ends_at=end)
                )
                self.assertEqual(response.status_code, 302)

    def test_blank_page_has_no_confirm_button(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, CONFIRM)
        self.assertContains(response, "Schedule match")

    def test_cancelled_match_does_not_warn(self):
        self.conflict.cancel()
        response = self.client.post(self.url, self.post_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Match.objects.count(), 2)

    def test_made_up_confirmation_only_warns_again(self):
        self.assertEqual(self.confirm("yes").status_code, 200)
        self.assertEqual(self.confirm("").status_code, 200)
        self.assertEqual(Match.objects.count(), 1)

    def test_stale_confirm_after_changing_the_time_warns_again(self):
        moved = {"starts_at": "2026-11-10T19:00", "ends_at": "2026-11-10T21:00"}
        token = self.warn()
        response = self.confirm(token, **moved)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Match.objects.count(), 1)
        form = response.context["form"]
        self.assertEqual(form.overlaps, [self.conflict])
        self.assertNotEqual(form.overlap_token, token)
        # The new warning can be confirmed in turn.
        self.assertEqual(self.confirm(form.overlap_token, **moved).status_code, 302)
        self.assertEqual(Match.objects.count(), 2)

    def test_stale_confirm_after_changing_the_facility_warns_again(self):
        other = self.build(
            home_team=self.hawks, away_team=self.owls, facility=self.second_field
        )
        other.save()
        response = self.confirm(self.warn(), facility=self.second_field.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].overlaps, [other])
        self.assertContains(response, "Paulson already has 1 match")
        self.assertEqual(Match.objects.count(), 2)

    def test_stale_confirm_is_harmless_once_there_is_no_conflict(self):
        response = self.confirm(
            self.warn(), starts_at="2026-11-10T20:00", ends_at="2026-11-10T21:00"
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Match.objects.count(), 2)

    def test_confirm_does_not_cover_a_conflict_added_after_the_warning(self):
        token = self.warn()
        self.build(home_team=self.hawks, away_team=self.owls).save()
        self.assertEqual(self.confirm(token).status_code, 200)
        self.assertEqual(Match.objects.count(), 2)

    def test_confirm_does_not_cover_a_conflict_moved_after_the_warning(self):
        token = self.warn()
        Match.objects.filter(pk=self.conflict.pk).update(ends_at=at(10, 22))
        self.assertEqual(self.confirm(token).status_code, 200)
        self.assertEqual(Match.objects.count(), 1)

    def test_editing_a_match_does_not_conflict_with_itself(self):
        response = self.client.post(
            reverse("matches:edit", args=[self.conflict.pk]),
            self.post_data(
                home_team=self.hawks.pk,
                away_team=self.owls.pk,
                ends_at="2026-11-10T19:00",
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.ends_at, at(10, 19))

    def test_rescheduling_into_a_conflict_warns_then_saves(self):
        match = self.build(starts_at=at(12, 18), ends_at=at(12, 20))
        match.save()
        url = reverse("matches:edit", args=[match.pk])
        response = self.client.post(url, self.post_data())
        self.assertContains(response, "Save anyway")
        match.refresh_from_db()
        self.assertEqual(match.starts_at, at(12, 18))
        token = response.context["form"].overlap_token
        self.assertEqual(self.confirm(token, url).status_code, 302)
        match.refresh_from_db()
        self.assertEqual(match.starts_at, at(10, 18))

    def test_invalid_form_does_not_warn(self):
        for data in [
            # Backwards, and inside the existing match, so only the end-after-start
            # check keeps it out of the overlap query.
            self.post_data(starts_at="2026-11-10T19:00", ends_at="2026-11-10T18:30"),
            self.post_data(starts_at="not a date"),
            self.post_data(facility=""),
        ]:
            with self.subTest(data=data):
                response = self.client.post(self.url, data)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["form"].overlaps, [])
                self.assertTrue(response.context["form"].errors)

    def test_confirming_does_not_bypass_other_errors(self):
        response = self.confirm(self.warn(), away_team=self.home.pk)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("away_team"))
        self.assertEqual(Match.objects.count(), 1)
