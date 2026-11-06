"""Create or reset a verified player account from environment variables.

The testing site has no email backend for sign-up verification, so
.ebextensions/django.config runs this after migrate on every deploy. Reads
TEST_PLAYER_EMAIL and TEST_PLAYER_PASSWORD (set with `eb setenv`) and does nothing
when either is missing.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.roles import CASUAL_PLAYER_ROLE, assign_role


class Command(BaseCommand):
    help = "Create or reset the player account named by TEST_PLAYER_EMAIL."

    def handle(self, *args, **options):
        email = os.environ.get("TEST_PLAYER_EMAIL", "").strip().lower()
        password = os.environ.get("TEST_PLAYER_PASSWORD", "")
        if not email or not password:
            self.stdout.write("TEST_PLAYER_EMAIL or TEST_PLAYER_PASSWORD not set.")
            return

        # Same shape as a verified sign-up: the email is the username.
        user, created = get_user_model().objects.get_or_create(
            username=email, defaults={"email": email}
        )
        user.email = email
        user.is_active = True
        user.set_password(password)
        user.save()
        assign_role(user, CASUAL_PLAYER_ROLE)
        self.stdout.write(f"{'Created' if created else 'Reset'} player {email}.")
