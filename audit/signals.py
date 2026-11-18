"""Log every create/update/delete of the League Admin-managed models.

The actor comes from AuditMiddleware's thread-local: web changes are
attributed to the signed-in user, shell and seed-script changes log None.

Bulk seed scripts wrap their writes in ``muted()`` so demo data logs nothing.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save

from facilities.models import Facility
from matches.models import Match
from teams.models import Season, Sport, Team

from .middleware import get_current_user
from .models import AuditLog

WATCHED_MODELS = (Team, Season, Sport, Match, Facility)

# A ContextVar, so a mute in one thread or task never silences another.
_muted = ContextVar("audit_muted", default=False)


@contextmanager
def muted():
    """Write no audit rows inside this block. For seed scripts only.

    Only the current thread or async task is muted, and the previous state
    comes back on exit, also after an exception.
    """
    token = _muted.set(True)
    try:
        yield
    finally:
        _muted.reset(token)


def is_muted():
    return _muted.get()


def _actor():
    """Logged-in saved user, else None. An unsaved user cannot be the actor."""
    user = get_current_user()
    if user is None or not user.pk:
        return None
    return user


def _log(instance, action):
    if is_muted():
        return
    AuditLog.objects.create(
        actor=_actor(),
        action=action,
        object_type=type(instance).__name__,
        object_id=str(instance.pk),
        object_repr=str(instance)[:200],
    )


def _on_save(sender, instance, created, **kwargs):
    if created:
        action = AuditLog.Action.CREATED
    else:
        action = AuditLog.Action.UPDATED
    _log(instance, action)


def _on_delete(sender, instance, **kwargs):
    _log(instance, AuditLog.Action.DELETED)


for _model in WATCHED_MODELS:
    post_save.connect(
        _on_save,
        sender=_model,
        dispatch_uid=f"audit-log-save-{_model.__name__}",
    )
    post_delete.connect(
        _on_delete,
        sender=_model,
        dispatch_uid=f"audit-log-delete-{_model.__name__}",
    )
