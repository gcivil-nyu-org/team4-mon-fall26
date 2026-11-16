"""League Admins grant and remove the Scorekeeper and League Admin roles (#261).

change_role holds the rules. It locks the role's Group row, so changes to one
role run one after another, then reads everything again under the lock.
accounts/roles.py must not import this module: matches/models.py imports roles.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Exists, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.dispatch import Signal

from audit.models import AuditLog
from core.names import display_name
from matches.models import Match

from .roles import LEAGUE_ADMIN_ROLE, SCOREKEEPER_ROLE, has_role

MANAGED_ROLES = {"scorekeeper": SCOREKEEPER_ROLE, "league_admin": LEAGUE_ADMIN_ROLE}

SELF_MESSAGE = "You can't remove your own League Admin role. Ask another League Admin."
LAST_MESSAGE = (
    "{name} is the last League Admin. Make someone else a League Admin first."
)

role_changed = Signal()
"""Sent after a role change, with user=, role= (group name), granted= and actor=."""


class RoleChangeRefused(Exception):
    """A safety rule refused the change. str(error) is the message to show."""


def can_manage_roles(user):
    # has_role runs a fresh query, so a role removed a moment ago counts.
    return bool(
        getattr(user, "is_superuser", False) or has_role(user, LEAGUE_ADMIN_ROLE)
    )


def listable_users():
    """Active, signed-up users. Placeholders and unverified sign-ups drop out."""
    return get_user_model().objects.filter(is_active=True, pending_account__isnull=True)


def league_admin_count():
    """Listable holders of the League Admin group. is_superuser adds nothing."""
    return listable_users().filter(groups__name=LEAGUE_ADMIN_ROLE).distinct().count()


def unscored_match_count(user):
    return Match.objects.unscored().filter(scorekeeper=user).count()


def _holds(role_name):
    memberships = get_user_model().groups.through.objects
    return Exists(memberships.filter(user=OuterRef("pk"), group__name=role_name))


def role_rows():
    """The roles page rows, with role flags and unscored match counts."""
    unscored = (
        Match.objects.unscored()
        .filter(scorekeeper=OuterRef("pk"))
        .order_by()
        .values("scorekeeper")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return (
        listable_users()
        .annotate(
            is_scorekeeper=_holds(SCOREKEEPER_ROLE),
            is_league_admin=_holds(LEAGUE_ADMIN_ROLE),
            unscored_matches=Coalesce(
                Subquery(unscored, output_field=IntegerField()), 0
            ),
        )
        .order_by("first_name", "last_name", "email", "pk")
    )


def change_role(actor, target, role_name, grant):
    """Grant or remove one role. True when something changed.

    Raises ValueError for a role this page doesn't manage, PermissionDenied when
    the actor can't manage roles, and RoleChangeRefused for the League Admin
    safety rules.
    """
    if role_name not in MANAGED_ROLES.values():
        raise ValueError(role_name)
    with transaction.atomic():
        # Every change to one role waits on this row (spec R8).
        group, _ = Group.objects.select_for_update().get_or_create(name=role_name)
        if not can_manage_roles(actor):  # read again under the lock
            raise PermissionDenied("League Admin access is required.")
        held = target.groups.filter(pk=group.pk).exists()
        if held == grant:
            return False
        if not grant and role_name == LEAGUE_ADMIN_ROLE:
            if target.pk == actor.pk:
                raise RoleChangeRefused(SELF_MESSAGE)
            if league_admin_count() <= 1:
                raise RoleChangeRefused(LAST_MESSAGE.format(name=display_name(target)))
        if grant:
            target.groups.add(group)
        else:
            target.groups.remove(group)
        preposition = "to" if grant else "from"
        AuditLog.objects.create(
            actor=actor,
            action=AuditLog.Action.GRANTED if grant else AuditLog.Action.REMOVED,
            object_type="Role",
            object_id=str(target.pk),
            object_repr=f"{role_name} {preposition} {display_name(target)}"[:200],
        )
        role_changed.send(
            sender=change_role, user=target, role=role_name, granted=grant, actor=actor
        )
    return True
