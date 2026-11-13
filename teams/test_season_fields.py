"""Season-first team and free agent forms (#191): the season sets the sport and the divisions."""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import FreeAgentRequestForm, TeamCreateForm, season_label
from .models import Division, FreeAgentRequest, Roster, Season, Sport, Team
from .season_rules import SeasonState

START = datetime.date(2026, 9, 1)


def make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@nyu.edu", password="pass12345!"
    )


class SeasonFieldsBase(TestCase):
    def setUp(self):
        self.basketball = Sport.objects.create(name="Basketball")
        self.soccer = Sport.objects.create(name="Soccer")
        self.season = Season.objects.create(
            name="Fall 2026 Basketball",
            start_date=START,
            state=SeasonState.OPEN,
            sport=self.basketball,
        )
        self.any_season = Season.objects.create(
            name="Custom League", start_date=START, state=SeasonState.OPEN
        )
        self.tandon = Division.objects.create(season=self.season, name="Tandon")
        self.stern = Division.objects.create(season=self.season, name="Stern")
        self.custom_division = Division.objects.create(
            season=self.any_season, name="East"
        )
        self.user = make_user("player1")


class SeasonLabelTests(SeasonFieldsBase):
    def test_name_that_has_the_sport_stays_as_is(self):
        self.assertEqual(season_label(self.season), "Fall 2026 Basketball")

    def test_name_without_the_sport_gets_it(self):
        season = Season(name="Winter Cup", sport=self.soccer)
        self.assertEqual(season_label(season), "Winter Cup (Soccer)")

    def test_season_with_no_sport_says_any_sport(self):
        self.assertEqual(season_label(self.any_season), "Custom League (any sport)")


class TeamFormSeasonFirstTests(SeasonFieldsBase):
    def form(self, **data):
        data.setdefault("name", "Violets")
        return TeamCreateForm(data, user=self.user)

    def test_season_comes_before_sport_and_division(self):
        self.assertEqual(
            list(TeamCreateForm(user=self.user).fields),
            ["name", "season", "sport", "division"],
        )

    def test_blank_sport_takes_the_season_sport(self):
        # A disabled select sends nothing.
        form = self.form(season=self.season.pk)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save(commit=False).sport, self.basketball)

    def test_another_sport_is_replaced_by_the_season_sport(self):
        form = self.form(season=self.season.pk, sport=self.soccer.pk)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sport"], self.basketball)

    def test_unknown_sport_value_is_refused(self):
        form = self.form(season=self.season.pk, sport="999999")
        self.assertFalse(form.is_valid())
        self.assertIn("sport", form.errors)

    def test_season_with_no_sport_needs_a_sport(self):
        form = self.form(season=self.any_season.pk)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["sport"], ["This field is required."])

    def test_season_with_no_sport_keeps_the_chosen_sport(self):
        form = self.form(season=self.any_season.pk, sport=self.soccer.pk)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sport"], self.soccer)

    def test_no_season_needs_a_sport(self):
        form = self.form(season="")
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["sport"], ["This field is required."])
        form = self.form(season="", sport=self.soccer.pk)
        self.assertTrue(form.is_valid(), form.errors)

    def test_season_error_adds_no_sport_error(self):
        team = Team.objects.create(
            name="Hoopers", sport=self.basketball, season=self.season, captain=self.user
        )
        Roster.objects.create(team=team, player=self.user, role=Roster.Role.CAPTAIN)
        form = self.form(season=self.season.pk)
        self.assertFalse(form.is_valid())
        self.assertEqual(list(form.errors), ["season"])

    def test_division_from_another_season_is_refused(self):
        form = self.form(season=self.season.pk, division=self.custom_division.pk)
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["division"], ["Choose a division from the selected season."]
        )

    def test_division_with_no_season_is_refused(self):
        form = self.form(season="", sport=self.soccer.pk, division=self.tandon.pk)
        self.assertFalse(form.is_valid())
        self.assertIn("division", form.errors)

    def test_division_of_a_closed_season_is_not_offered(self):
        closed = Season.objects.create(
            name="Spring 2026 Soccer", start_date=START, state=SeasonState.CLOSED
        )
        division = Division.objects.create(season=closed, name="Tandon")
        form = self.form(season=self.season.pk, division=division.pk)
        self.assertFalse(form.is_valid())
        self.assertIn("division", form.errors)

    def test_divisions_are_grouped_by_season(self):
        choices = list(TeamCreateForm(user=self.user).fields["division"].choices)
        self.assertEqual(
            choices,
            [
                ("", "No division"),
                ("Custom League (any sport)", [(self.custom_division.pk, "East")]),
                (
                    "Fall 2026 Basketball",
                    [(self.stern.pk, "Stern"), (self.tandon.pk, "Tandon")],
                ),
            ],
        )

    def test_season_rules_list_each_season_sport_and_divisions(self):
        rules = TeamCreateForm(user=self.user).season_rules
        self.assertEqual(
            rules,
            {
                str(self.season.pk): {
                    "sport": str(self.basketball.pk),
                    "divisions": [str(self.stern.pk), str(self.tandon.pk)],
                },
                str(self.any_season.pk): {
                    "sport": "",
                    "divisions": [str(self.custom_division.pk)],
                },
            },
        )

    def test_create_view_saves_season_sport_and_division(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("teams:create"),
            {"name": "Violets", "season": self.season.pk, "division": self.tandon.pk},
        )
        team = Team.objects.get()
        self.assertRedirects(response, reverse("teams:detail", args=[team.pk]))
        self.assertEqual(team.sport, self.basketball)
        self.assertEqual(team.division, self.tandon)

    def test_create_page_renders_optgroups_hint_and_script(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("teams:create"))
        self.assertContains(response, '<optgroup label="Fall 2026 Basketball">')
        self.assertContains(response, "Custom League (any sport)")
        self.assertContains(response, "The season sets the sport.")
        self.assertContains(response, 'id="pn-season-rules"')
        self.assertContains(response, "js/season_fields.js")
        content = response.content.decode()
        self.assertLess(content.index('name="season"'), content.index('name="sport"'))


class FreeAgentFormSeasonFirstTests(SeasonFieldsBase):
    def form(self, **data):
        return FreeAgentRequestForm(data, user=self.user)

    def test_blank_sport_takes_the_season_sport(self):
        form = self.form(season=self.season.pk)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sport"], self.basketball)

    def test_another_sport_is_replaced_by_the_season_sport(self):
        form = self.form(season=self.season.pk, sport=self.soccer.pk)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sport"], self.basketball)

    def test_season_with_no_sport_needs_a_sport(self):
        form = self.form(season=self.any_season.pk)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["sport"], ["This field is required."])
        form = self.form(season=self.any_season.pk, sport=self.soccer.pk)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["sport"], self.soccer)

    def test_missing_season_adds_no_sport_error(self):
        form = self.form()
        self.assertFalse(form.is_valid())
        self.assertEqual(list(form.errors), ["season"])

    def test_division_from_another_season_is_refused(self):
        form = self.form(season=self.season.pk, division=self.custom_division.pk)
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["division"], ["Choose a division from the selected season."]
        )

    def test_divisions_are_grouped_by_season(self):
        groups = [
            label
            for label, _ in FreeAgentRequestForm(user=self.user)
            .fields["division"]
            .choices
        ]
        self.assertEqual(
            groups, ["", "Custom League (any sport)", "Fall 2026 Basketball"]
        )

    def test_pool_view_saves_season_sport_and_division(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("teams:free_agent_pool"),
            {"season": self.season.pk, "division": self.stern.pk},
        )
        self.assertRedirects(response, reverse("teams:free_agent_pool"))
        request = FreeAgentRequest.objects.get()
        self.assertEqual(request.sport, self.basketball)
        self.assertEqual(request.division, self.stern)

    def test_pool_page_renders_optgroups_and_script(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("teams:free_agent_pool"))
        self.assertContains(response, '<optgroup label="Fall 2026 Basketball">')
        self.assertContains(response, 'id="pn-season-rules"')
        self.assertContains(response, "js/season_fields.js")
