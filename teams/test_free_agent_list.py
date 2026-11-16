from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .forms import FreeAgentFilterForm
from .models import Division, FreeAgentRequest, Sport
from .season_rules import SeasonState
from .tests import make_season, make_user


class FreeAgentFilterFormTests(TestCase):
    def setUp(self):
        self.season = make_season()
        self.other_season = make_season(name="Spring 2027")
        self.closed = make_season(name="Spring 2026", state=SeasonState.CLOSED)
        self.division = Division.objects.create(season=self.season, name="Division A")
        self.other_division = Division.objects.create(
            season=self.other_season, name="Division B"
        )
        self.sport = Sport.objects.get_or_create(name="Soccer")[0]
        self.hoops = Sport.objects.get_or_create(name="Basketball")[0]
        self.soccer_request = FreeAgentRequest.objects.create(
            player=make_user("p1"),
            season=self.season,
            sport=self.sport,
            division=self.division,
        )
        self.hoops_request = FreeAgentRequest.objects.create(
            player=make_user("p2"), season=self.other_season, sport=self.hoops
        )

    def filtered(self, data):
        return FreeAgentFilterForm(data).filter(FreeAgentRequest.objects.all())

    def test_ids_do_not_collide_with_the_request_form(self):
        self.assertIn('id="filter_season"', str(FreeAgentFilterForm()["season"]))

    def test_closed_and_draft_seasons_are_not_choices(self):
        draft = make_season(name="Draft", state=SeasonState.DRAFT)
        queryset = FreeAgentFilterForm().fields["season"].queryset
        self.assertNotIn(self.closed, queryset)
        self.assertNotIn(draft, queryset)

    def test_divisions_are_grouped_by_season(self):
        html = str(FreeAgentFilterForm()["division"])
        self.assertIn("<optgroup", html)
        self.assertIn("Division A", html)

    def test_invalid_values_are_ignored_one_by_one(self):
        qs = self.filtered({"season": "abc", "sport": self.sport.pk})
        # sport still applies, season does not
        self.assertQuerySetEqual(qs, [self.soccer_request], ordered=False)

    def test_closed_season_pk_is_ignored(self):
        qs = self.filtered({"season": self.closed.pk})
        self.assertQuerySetEqual(
            qs, [self.soccer_request, self.hoops_request], ordered=False
        )

    def test_division_from_another_season_is_dropped(self):
        form = FreeAgentFilterForm(
            {"season": self.other_season.pk, "division": self.division.pk}
        )
        qs = form.filter(FreeAgentRequest.objects.all())
        self.assertEqual(form.errors, {})
        self.assertQuerySetEqual(qs, [self.hoops_request], ordered=False)

    def test_no_data_is_unfiltered(self):
        qs = FreeAgentFilterForm().filter(FreeAgentRequest.objects.all())
        self.assertEqual(qs.count(), 2)

    def test_each_filter_narrows(self):
        cases = {
            "season": ({"season": self.season.pk}, [self.soccer_request]),
            "sport": ({"sport": self.hoops.pk}, [self.hoops_request]),
            "division": ({"division": self.division.pk}, [self.soccer_request]),
        }
        for name, (data, expected) in cases.items():
            with self.subTest(name):
                self.assertQuerySetEqual(self.filtered(data), expected, ordered=False)


class FreeAgentListPageTests(TestCase):
    def setUp(self):
        self.season = make_season()
        self.sport = Sport.objects.get_or_create(name="Soccer")[0]
        self.viewer = make_user("viewer")
        self.alex = make_user("alex")
        self.alex.first_name, self.alex.last_name = "Alex", "Lee"
        self.alex.save()
        self.noname = make_user("noname")
        for player in (self.viewer, self.alex, self.noname):
            self.add_request(player)
        self.url = reverse("teams:free_agent_pool")
        self.client.force_login(self.viewer)

    def add_request(self, player, season=None, sport=None):
        return FreeAgentRequest.objects.create(
            player=player, season=season or self.season, sport=sport or self.sport
        )

    def listed(self, response):
        return [item.player for item in response.context["free_agents"]]

    def test_other_players_are_listed(self):
        self.assertContains(self.client.get(self.url), "Alex Lee")

    def test_own_row_is_highlighted(self):
        self.assertContains(self.client.get(self.url), "pn-row-me", count=1)

    def test_nameless_player_shows_fallback(self):
        self.assertContains(self.client.get(self.url), "PlayNYU player")

    def test_no_email_on_the_page(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "alex@nyu.edu")
        self.assertNotContains(response, "noname@nyu.edu")

    def test_closed_season_requests_are_hidden(self):
        closed = make_season(name="Spring 2026", state=SeasonState.CLOSED)
        old = make_user("old")
        self.add_request(old, season=closed)
        self.assertNotIn(old, self.listed(self.client.get(self.url)))

    def test_draft_season_requests_are_hidden_from_admins_too(self):
        draft = make_season(name="Draft", state=SeasonState.DRAFT)
        drafted = make_user("drafted")
        self.add_request(drafted, season=draft)
        admin = make_user("admin")
        admin.is_superuser = True
        admin.save()
        self.client.force_login(admin)
        self.assertNotIn(drafted, self.listed(self.client.get(self.url)))

    def test_inactive_player_is_hidden(self):
        self.alex.is_active = False
        self.alex.save()
        self.assertNotContains(self.client.get(self.url), "Alex Lee")

    def test_bad_filter_gives_200(self):
        for value in ("abc", "99999"):
            with self.subTest(value):
                response = self.client.get(self.url, {"season": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["free_agents"].paginator.count, 3)

    def test_second_page_keeps_filters(self):
        sport = Sport.objects.create(name="Tennis")
        for i in range(25):
            self.add_request(make_user(f"t{i}"), sport=sport)
        response = self.client.get(self.url, {"sport": sport.pk, "page": 2})
        self.assertEqual(len(response.context["free_agents"]), 5)
        self.assertContains(response, f"sport={sport.pk}&amp;page=1")
        self.assertContains(response, 'aria-label="Free agent pages"')

    def test_query_count_is_constant(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.client.get(self.url)
            return len(queries)

        few = count()
        for i in range(30):
            self.add_request(make_user(f"q{i}"))
        self.assertEqual(count(), few)

    def test_empty_state(self):
        FreeAgentRequest.objects.all().delete()
        self.assertContains(self.client.get(self.url), "No free agents yet")

    def test_filtered_empty_state(self):
        other = Sport.objects.create(name="Volleyball")
        response = self.client.get(self.url, {"sport": other.pk})
        self.assertContains(response, "No free agents match these filters.")

    def test_visibility_notice_on_the_request_form(self):
        FreeAgentRequest.objects.filter(player=self.viewer).delete()
        self.assertContains(
            self.client.get(self.url),
            "Other players can see your name, sport and division.",
        )
