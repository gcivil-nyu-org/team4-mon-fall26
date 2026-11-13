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


def _log(instance, action):
    if _muted.get():
        return
    actor = get_current_user()
    AuditLog.objects.create(
        actor=actor if actor is not None and actor.pk else None,
        action=action,
        object_type=type(instance).__name__,
        object_id=str(instance.pk),
        object_repr=str(instance)[:200],
    )


def _register(model):
    def _saved(sender, instance, created, **kwargs):
        _log(instance, AuditLog.Action.CREATED if created else AuditLog.Action.UPDATED)

    def _deleted(sender, instance, **kwargs):
        _log(instance, AuditLog.Action.DELETED)

    post_save.connect(
        _saved, sender=model, dispatch_uid=f"audit-log-save-{model.__name__}"
    )
    post_delete.connect(
        _deleted, sender=model, dispatch_uid=f"audit-log-delete-{model.__name__}"
    )


for _model in WATCHED_MODELS:
    _register(_model)
