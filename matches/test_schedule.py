import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from facilities.models import Facility
from teams.models import Division, Roster, Season, Team
from teams.season_rules import SeasonState

from .tests import MatchFixtures, make_user


def hours_from_now(hours):
    return timezone.now() + datetime.timedelta(hours=hours)


class ScheduleFixtures(MatchFixtures):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gold = Division.objects.create(season=cls.season, name="Gold")
        cls.silver = Division.objects.create(season=cls.season, name="Silver")
        cls.home.division = cls.gold
        cls.home.save()
        cls.away.division = cls.gold
        cls.away.save()
        cls.third = cls.make_team("Terriers", cls.soccer, cls.season)
        cls.third.division = cls.silver
        cls.third.save()
        Roster.objects.create(team=cls.home, player=cls.player)

    def setUp(self):
        self.client.force_login(self.player)

    def add_match(self, start=24, length=2, **overrides):
        match = self.build(
            starts_at=hours_from_now(start),
            ends_at=hours_from_now(start + length),
            **overrides,
        )
        match.save()
        return match

    def add_other_season_match(self):
        match = self.build(
            season=self.other_season,
            home_team=self.outsider,
            away_team=self.make_team("Rivals", self.soccer, self.other_season),
            starts_at=hours_from_now(1),
            ends_at=hours_from_now(2),
        )
        match.save()
        return match

    def make_draft(self):
        Season.objects.get(pk=self.season.pk).move_to(SeasonState.DRAFT)


class SeasonListTests(ScheduleFixtures):
    url = reverse("matches:schedule_seasons")

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_lists_seasons_and_is_in_the_nav(self):
        response = self.client.get(self.url)
        self.assertContains(
            response, reverse("matches:season_schedule", args=[self.season.pk])
        )
        self.assertContains(response, f'href="{self.url}" aria-current="page"')

    def test_players_do_not_see_draft_seasons(self):
        self.make_draft()
        response = self.client.get(self.url)
        self.assertNotIn(self.season, response.context["seasons"])
        self.assertIn(self.other_season, response.context["seasons"])

    def test_league_admins_see_draft_seasons(self):
        self.make_draft()
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertIn(self.season, response.context["seasons"])

    def test_empty_state(self):
        Season.objects.update(state=SeasonState.DRAFT)
        self.assertContains(self.client.get(self.url), "No seasons yet")


class SeasonScheduleTests(ScheduleFixtures):
    def url(self, season=None):
        season = season or self.season
        return reverse("matches:season_schedule", args=[season.pk])

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_lists_only_this_seasons_matches_sorted_by_time(self):
        later = self.add_match(start=48)
        sooner = self.add_match(start=24)
        past = self.add_match(start=-48)
        self.add_other_season_match()
        response = self.client.get(self.url())
        self.assertEqual(list(response.context["matches"]), [past, sooner, later])

    def test_unknown_season_is_404(self):
        for pk in (999999, 10**30):
            url = reverse("matches:season_schedule", args=[pk])
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_filter_by_division(self):
        gold = self.add_match(start=24)
        silver = self.add_match(
            start=48, home_team=self.third, away_team=self.hoops_team
        )
        response = self.client.get(self.url(), {"division": self.silver.pk})
        self.assertEqual(list(response.context["matches"]), [silver])
        self.assertEqual(response.context["division"], self.silver)
        self.assertContains(response, f'value="{self.silver.pk}" selected')
        response = self.client.get(self.url(), {"division": self.gold.pk})
        self.assertEqual(list(response.context["matches"]), [gold])

    def test_match_inside_a_division_is_listed_once(self):
        match = self.add_match()
        response = self.client.get(self.url(), {"division": self.gold.pk})
        self.assertEqual(list(response.context["matches"]), [match])

    def test_cross_division_match_is_on_both_schedules(self):
        match = self.add_match(home_team=self.home, away_team=self.third)
        for division in (self.gold, self.silver):
            response = self.client.get(self.url(), {"division": division.pk})
            self.assertEqual(list(response.context["matches"]), [match])

    def test_bad_filter_values_show_every_match(self):
        match = self.add_match()
        foreign = Division.objects.create(season=self.other_season, name="Gold")
        for value in ("", "abc", "-1", "1.5", "999999", "9" * 40, "\x00", foreign.pk):
            response = self.client.get(self.url(), {"division": value})
            self.assertEqual(response.status_code, 200, value)
            self.assertIsNone(response.context["division"], value)
            self.assertEqual(list(response.context["matches"]), [match], value)

    def test_season_without_divisions(self):
        match = self.add_other_season_match()
        response = self.client.get(self.url(self.other_season))
        self.assertEqual(list(response.context["matches"]), [match])
        self.assertNotContains(response, 'name="division"')
        response = self.client.get(self.url(self.other_season), {"division": "1"})
        self.assertEqual(list(response.context["matches"]), [match])

    def test_division_filter_shown_when_season_has_divisions(self):
        self.assertContains(self.client.get(self.url()), 'name="division"')

    def test_cancelled_match_is_shown_and_marked(self):
        match = self.add_match()
        self.assertNotContains(self.client.get(self.url()), "Cancelled")
        match.cancel()
        response = self.client.get(self.url())
        self.assertEqual(list(response.context["matches"]), [match])
        self.assertContains(response, ">Cancelled</span>")

    def test_facility_links_to_details(self):
        self.add_match()
        detail = reverse("facilities:detail", args=[self.field.pk])
        self.assertContains(self.client.get(self.url()), f'href="{detail}"')

    def test_inactive_facility_has_no_link(self):
        closed = Facility.objects.create(
            name="Old Gym", source=Facility.Source.NYU, is_active=False
        )
        self.add_match(facility=closed)
        detail = reverse("facilities:detail", args=[closed.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        response = self.client.get(self.url())
        self.assertContains(response, "Old Gym")
        self.assertNotContains(response, detail)

    def test_draft_season_is_hidden_from_players(self):
        self.make_draft()
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_league_admin_and_superuser_can_see_draft_season(self):
        self.make_draft()
        superuser = make_user("root")
        superuser.is_superuser = True
        superuser.save()
        for user in (self.admin, superuser):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_closed_season_is_visible(self):
        Season.objects.filter(pk=self.season.pk).update(state=SeasonState.CLOSED)
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_empty_states(self):
        self.assertContains(self.client.get(self.url()), "No matches yet")
        self.add_match()
        response = self.client.get(self.url(), {"division": self.silver.pk})
        self.assertContains(response, "No matches in Silver")

    def test_query_count_does_not_grow_with_matches(self):
        self.add_match()
        with CaptureQueriesContext(connection) as one_match:
            self.client.get(self.url())
        for hours in range(30, 60, 3):
            self.add_match(start=hours, home_team=self.third, away_team=self.away)
        with CaptureQueriesContext(connection) as many_matches:
            self.client.get(self.url())
        self.assertEqual(len(one_match), len(many_matches))


class TeamScheduleTests(ScheduleFixtures):
    def url(self, team=None):
        return reverse("teams:detail", args=[(team or self.home).pk])

    def test_splits_upcoming_and_past_nearest_first(self):
        later = self.add_match(start=48)
        sooner = self.add_match(start=24)
        older = self.add_match(start=-48)
        recent = self.add_match(start=-24, away_team=self.third)
        response = self.client.get(self.url())
        self.assertEqual(response.context["upcoming_matches"], [sooner, later])
        self.assertEqual(response.context["past_matches"], [recent, older])

    def test_includes_home_and_away_but_not_other_teams(self):
        home = self.add_match(start=24)
        away = self.add_match(start=48, home_team=self.third, away_team=self.home)
        self.add_match(start=72, home_team=self.third, away_team=self.away)
        response = self.client.get(self.url())
        self.assertEqual(response.context["upcoming_matches"], [home, away])

    def test_match_being_played_is_still_upcoming(self):
        match = self.add_match(start=-1, length=2)
        response = self.client.get(self.url())
        self.assertEqual(response.context["upcoming_matches"], [match])
        self.assertEqual(response.context["past_matches"], [])

    def test_cancelled_matches_are_shown_and_marked(self):
        upcoming = self.add_match(start=24)
        past = self.add_match(start=-24)
        upcoming.cancel()
        past.cancel()
        response = self.client.get(self.url())
        self.assertEqual(response.context["upcoming_matches"], [upcoming])
        self.assertEqual(response.context["past_matches"], [past])
        self.assertContains(response, ">Cancelled</span>", count=2)

    def test_facility_link_only_when_active(self):
        closed = Facility.objects.create(
            name="Old Gym", source=Facility.Source.NYU, is_active=False
        )
        self.add_match(start=24)
        self.add_match(start=-24, facility=closed)
        response = self.client.get(self.url())
        self.assertContains(
            response, reverse("facilities:detail", args=[self.field.pk])
        )
        self.assertContains(response, "Old Gym")
        self.assertNotContains(response, reverse("facilities:detail", args=[closed.pk]))

    def test_empty_states_and_schedule_link(self):
        response = self.client.get(self.url())
        self.assertContains(response, "No upcoming matches")
        self.assertContains(response, "No past matches")
        self.assertContains(
            response, reverse("matches:season_schedule", args=[self.season.pk])
        )

    def test_team_without_a_season(self):
        team = Team.objects.create(
            name="Casuals", sport=self.soccer, captain=self.player
        )
        Roster.objects.create(team=team, player=self.player)
        response = self.client.get(self.url(team))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "View season schedule")

    def test_draft_season_matches_are_hidden_from_players(self):
        self.add_match(start=24)
        self.add_match(start=-24)
        self.make_draft()
        response = self.client.get(self.url())
        self.assertEqual(response.context["upcoming_matches"], [])
        self.assertEqual(response.context["past_matches"], [])
        self.assertNotContains(response, "View season schedule")

    def test_league_admin_sees_draft_season_matches(self):
        match = self.add_match(start=24)
        self.make_draft()
        self.client.force_login(self.admin)
        Roster.objects.create(team=self.home, player=self.admin)
        response = self.client.get(self.url())
        self.assertEqual(response.context["upcoming_matches"], [match])
        self.assertContains(response, "View season schedule")

    def test_non_members_still_cannot_see_the_team(self):
        self.client.force_login(make_user("stranger"))
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_query_count_does_not_grow_with_matches(self):
        self.add_match()
        with CaptureQueriesContext(connection) as one_match:
            self.client.get(self.url())
        for hours in range(30, 60, 3):
            self.add_match(start=hours)
            self.add_match(start=-hours)
        with CaptureQueriesContext(connection) as many_matches:
            self.client.get(self.url())
        self.assertEqual(len(one_match), len(many_matches))
