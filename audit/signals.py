"""Log every create/update/delete of the League Admin-managed models.

The actor comes from AuditMiddleware's thread-local: web changes are
attributed to the signed-in user, shell and seed-script changes log None.

Bulk seed scripts wrap their writes in ``muted()`` so demo data logs nothing.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save, pre_save

from facilities.models import Facility
from matches.models import Match
from teams.models import Season, Sport, Team

from .middleware import get_current_user
from .models import AuditLog

SCORE_FIELDS = {"home_score", "away_score"}
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


def _log(instance, action, details=""):
    if is_muted():
        return
    AuditLog.objects.create(
        actor=_actor(),
        action=action,
        object_type=type(instance).__name__,
        object_id=str(instance.pk),
        object_repr=str(instance)[:200],
        details=details,
    )


def _score_text(scores):
    return "none" if None in scores else f"{scores[0]}–{scores[1]}"


def _remember_stored_score(sender, instance, update_fields=None, **kwargs):
    """Keep the stored score, so the log can show the old and the new one."""
    instance._audit_old_score = (None, None)
    if is_muted() or instance.pk is None:
        return
    if update_fields is not None and not SCORE_FIELDS.intersection(update_fields):
        # This save can't change the stored score.
        instance._audit_old_score = None
        return
    stored = sender.objects.filter(pk=instance.pk)
    instance._audit_old_score = stored.values_list(
        "home_score", "away_score"
    ).first() or (None, None)


def _score_change(instance):
    old = getattr(instance, "_audit_old_score", None)
    new = (instance.home_score, instance.away_score)
    if old is None or old == new:
        return ""
    if None in old:
        return f"Score entered: {_score_text(new)}"
    return f"Score corrected: {_score_text(old)} to {_score_text(new)}"


def _on_save(sender, instance, created, **kwargs):
    if created:
        action = AuditLog.Action.CREATED
    else:
        action = AuditLog.Action.UPDATED
    details = _score_change(instance) if sender is Match else ""
    _log(instance, action, details)


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

pre_save.connect(
    _remember_stored_score, sender=Match, dispatch_uid="audit-log-match-score"
)
