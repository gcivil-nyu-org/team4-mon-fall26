from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .roles import CASUAL_PLAYER_ROLE, LEAGUE_ADMIN_ROLE, has_role

ENV = {"TEST_PLAYER_EMAIL": " Player@NYU.edu ", "TEST_PLAYER_PASSWORD": "pass12345!"}


def run():
    out = StringIO()
    call_command("create_test_player", stdout=out)
    return out.getvalue()


class CreateTestPlayerCommandTests(TestCase):
    def test_does_nothing_without_both_variables(self):
        for env in ({}, {"TEST_PLAYER_EMAIL": "player@nyu.edu"}):
            with self.subTest(env=env), mock.patch.dict("os.environ", env, clear=True):
                self.assertIn("not set", run())
        self.assertFalse(get_user_model().objects.exists())

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_creates_a_verified_player_who_can_log_in(self):
        self.assertIn("Created player player@nyu.edu.", run())

        user = get_user_model().objects.get()
        self.assertEqual((user.username, user.email), ("player@nyu.edu",) * 2)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertTrue(has_role(user, CASUAL_PLAYER_ROLE))
        self.assertFalse(has_role(user, LEAGUE_ADMIN_ROLE))
        response = self.client.post(
            reverse("login"), {"username": "player@nyu.edu", "password": "pass12345!"}
        )
        self.assertEqual(response.status_code, 302)

    def test_rerun_resets_the_password_without_duplicating(self):
        with mock.patch.dict("os.environ", ENV, clear=True):
            run()
        new_env = dict(ENV, TEST_PLAYER_PASSWORD="different-pass-1")
        with mock.patch.dict("os.environ", new_env, clear=True):
            self.assertIn("Reset player player@nyu.edu.", run())

        user = get_user_model().objects.get()
        self.assertTrue(user.check_password("different-pass-1"))
