from django import forms
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from teams.models import Roster
from teams.tests import make_team, make_user

from .templatetags.ui import control, initials, sport_icon


class SmokeTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PlayNYU")

    def test_health_check(self):
        response = self.client.get(reverse("core:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "ok")


class UiFilterTests(TestCase):
    def test_initials_from_name(self):
        user = get_user_model()(first_name="alex", last_name="lee", email="al1@nyu.edu")
        self.assertEqual(initials(user), "AL")

    def test_initials_fall_back_to_email(self):
        user = get_user_model()(email="zz9@nyu.edu")
        self.assertEqual(initials(user), "Z")

    def test_sport_icon(self):
        self.assertEqual(sport_icon(" Soccer "), "ti-ball-football")
        self.assertEqual(sport_icon("Quidditch"), "ti-trophy")

    def test_control_adds_classes_and_error_state(self):
        class F(forms.Form):
            name = forms.CharField()
            kind = forms.ChoiceField(choices=[("a", "A")])

        form = F(data={})
        form.is_valid()
        self.assertIn('class="form-control is-invalid"', control(form["name"]))
        self.assertIn('class="form-select is-invalid"', control(form["kind"]))


class DashboardTests(TestCase):
    def setUp(self):
        self.user = make_user("alex")
        self.user.first_name = "Alex"
        self.user.save()
        self.url = reverse("core:home")

    def login(self):
        self.client.force_login(self.user)

    def join(self, team, player):
        Roster.objects.create(team=team, player=player)

    def test_anonymous_sees_landing_page(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(response, "Sign up with your NYU email")

    def test_signed_in_sees_dashboard_greeting(self):
        self.login()
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, "core/dashboard.html")
        self.assertContains(response, "Hi, Alex")

    def test_counts(self):
        mine = make_team(self.user, name="Violets")
        other_cap = make_user("cap")
        theirs = make_team(other_cap, name="Bobcats")
        self.join(theirs, self.user)
        both = make_user("both")
        self.join(mine, both)
        self.join(theirs, both)
        self.login()
        context = self.client.get(self.url).context
        self.assertEqual(context["team_count"], 2)
        self.assertEqual(context["captain_count"], 1)
        self.assertEqual(context["teammate_count"], 2)
        self.assertCountEqual(context["teammates"], [other_cap, both])

    def test_my_teams_link_and_captain_badge(self):
        mine = make_team(self.user, name="Violets")
        theirs = make_team(make_user("cap"), name="Bobcats")
        self.join(theirs, self.user)
        self.login()
        response = self.client.get(self.url)
        for team in (mine, theirs):
            self.assertContains(response, reverse("teams:detail", args=[team.pk]))
        self.assertContains(
            response, '<span class="badge bg-primary-lt">Captain</span>', 1
        )
        self.assertEqual(
            [e.team for e in response.context["entries"] if e.role == "captain"],
            [mine],
        )

    def test_empty_state(self):
        self.login()
        self.assertContains(self.client.get(self.url), "No teams yet")

    def test_other_teams_hidden(self):
        make_team(make_user("cap"), name="Strangers")
        self.login()
        response = self.client.get(self.url)
        self.assertNotContains(response, "Strangers")
        self.assertEqual(response.context["team_count"], 0)
