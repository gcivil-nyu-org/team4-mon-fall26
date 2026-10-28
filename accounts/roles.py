"""Account-level roles backed by Django's built-in groups."""

from django.contrib.auth.models import Group

CASUAL_PLAYER_ROLE = "Casual Player"
LEAGUE_ADMIN_ROLE = "League Admin"


def assign_role(user, role_name):
    group, _ = Group.objects.get_or_create(name=role_name)
    user.groups.add(group)
    return group


def has_role(user, role_name):
    return bool(
        getattr(user, "is_authenticated", False)
        and user.groups.filter(name=role_name).exists()
    )
