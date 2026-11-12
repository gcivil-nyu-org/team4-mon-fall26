"""Create or reset a fixed set of verified demo players.

.ebextensions/django.config runs this after migrate on every deploy, so the
accounts exist on a new database and their passwords stay known on an existing
one. Their teams and other data are kept. Every demo player gets the
password in DEMO_USERS_PASSWORD (set with `eb setenv`); the command does nothing
when it is missing. Locally: DEMO_USERS_PASSWORD=... python manage.py seed_demo_users
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.roles import CASUAL_PLAYER_ROLE, assign_role

# (email, first name, last name). Two captains and four players are enough to
# demo teams, divisions and free-agent matching.
DEMO_USERS = [
    ("demo.captain1@nyu.edu", "Alex", "Rivera"),
    ("demo.captain2@nyu.edu", "Sam", "Chen"),
    ("demo.player1@nyu.edu", "Jordan", "Patel"),
    ("demo.player2@nyu.edu", "Taylor", "Kim"),
    ("demo.player3@nyu.edu", "Morgan", "Lee"),
    ("demo.player4@nyu.edu", "Casey", "Nguyen"),
]


class Command(BaseCommand):
    help = "Create or reset the demo players listed in DEMO_USERS."

    def handle(self, *args, **options):
        password = os.environ.get("DEMO_USERS_PASSWORD", "")
        if not password:
            self.stdout.write("DEMO_USERS_PASSWORD not set.")
            return

        User = get_user_model()
        for email, first_name, last_name in DEMO_USERS:
            # Same shape as a verified sign-up: the email is the username.
            user, _ = User.objects.get_or_create(
                username=email, defaults={"email": email}
            )
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = True
            user.set_password(password)
            user.save()
            assign_role(user, CASUAL_PLAYER_ROLE)
        self.stdout.write(f"Seeded {len(DEMO_USERS)} demo players.")
