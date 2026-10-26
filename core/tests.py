from django import forms
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
