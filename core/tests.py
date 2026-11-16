from django import forms
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from teams.models import Roster
from teams.tests import make_team, make_user

from .templatetags.ui import control, display_name, initials, ordinal, sport_icon


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

    def test_initials_from_one_name(self):
        self.assertEqual(initials(get_user_model()(last_name="lee")), "L")

    def test_initials_never_use_email_or_username(self):
        user = get_user_model()(email="zz9@nyu.edu", username="zz9@nyu.edu")
        self.assertEqual(initials(user), "P")

    def test_initials_for_no_user(self):
        self.assertEqual(initials(None), "P")

    def test_labelled_avatar_never_shows_email(self):
        user = get_user_model()(email="zz9@nyu.edu", username="zz9@nyu.edu")
        html = render_to_string(
            "components/avatar.html", {"person": user, "labelled": True}
        )
        self.assertNotIn("zz9", html)
        self.assertIn('aria-label="PlayNYU player"', html)
        self.assertIn(">P</span>", html)

    def test_labelled_avatar_uses_full_name(self):
        user = get_user_model()(first_name="Alex", last_name="Lee", email="a@nyu.edu")
        html = render_to_string(
            "components/avatar.html", {"person": user, "labelled": True}
        )
        self.assertIn('aria-label="Alex Lee"', html)
        self.assertIn(">AL</span>", html)

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


class NameFilterTests(TestCase):
    def test_display_name_uses_full_name(self):
        user = get_user_model()(
            first_name="Alex", last_name="Lee", email="al@nyu.edu", username="al"
        )
        self.assertEqual(display_name(user), "Alex Lee")

    def test_display_name_never_shows_email_or_username(self):
        self.assertEqual(
            display_name(get_user_model()(email="al@nyu.edu", username="al@nyu.edu")),
            "PlayNYU player",
        )

    def test_ordinal(self):
        for n, text in [
            (1, "1st"),
            (2, "2nd"),
            (3, "3rd"),
            (4, "4th"),
            (11, "11th"),
            (12, "12th"),
            (13, "13th"),
            (21, "21st"),
            (22, "22nd"),
            (111, "111th"),
        ]:
            self.assertEqual(ordinal(n), text)


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

    def test_landing_page_describes_current_features(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "coming soon")
        for text in ("Schedules and standings", "Facilities map", "Team chat"):
            self.assertContains(response, text)

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
        self.assertEqual(len(context["entries"]), 2)
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
        self.assertEqual(len(response.context["entries"]), 0)
