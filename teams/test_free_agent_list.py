from django.test import TestCase

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
