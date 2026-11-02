from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .management.commands.seed_demo_users import DEMO_USERS
from .roles import CASUAL_PLAYER_ROLE, LEAGUE_ADMIN_ROLE, has_role

ENV = {"DEMO_USERS_PASSWORD": "demo-pass-123"}


def run():
    out = StringIO()
    call_command("seed_demo_users", stdout=out)
    return out.getvalue()


class SeedDemoUsersCommandTests(TestCase):
    @mock.patch.dict("os.environ", {}, clear=True)
    def test_does_nothing_without_a_password(self):
        self.assertIn("not set", run())
        self.assertFalse(get_user_model().objects.exists())

    @mock.patch.dict("os.environ", ENV, clear=True)
    def test_creates_verified_players_who_can_log_in(self):
        self.assertIn(f"Seeded {len(DEMO_USERS)} demo players.", run())

        users = get_user_model().objects.order_by("username")
        self.assertEqual(
            [user.username for user in users],
            sorted(email for email, _, _ in DEMO_USERS),
        )
        for user in users:
            with self.subTest(user=user.username):
                self.assertTrue(user.is_active)
                self.assertTrue(user.first_name)
                self.assertFalse(user.is_superuser)
                self.assertTrue(has_role(user, CASUAL_PLAYER_ROLE))
                self.assertFalse(has_role(user, LEAGUE_ADMIN_ROLE))

        email = DEMO_USERS[0][0]
        response = self.client.post(
            reverse("login"), {"username": email, "password": "demo-pass-123"}
        )
        self.assertEqual(response.status_code, 302)

    def test_rerun_resets_passwords_without_duplicating(self):
        with mock.patch.dict("os.environ", ENV, clear=True):
            run()
        with mock.patch.dict(
            "os.environ", {"DEMO_USERS_PASSWORD": "new-pass-456"}, clear=True
        ):
            run()

        self.assertEqual(get_user_model().objects.count(), len(DEMO_USERS))
        user = get_user_model().objects.get(username=DEMO_USERS[0][0])
        self.assertTrue(user.check_password("new-pass-456"))
