"""Receivers that create notifications.

All receivers live in this app (connected on import from apps.ready), so
matches/, teams/ and core/ are never edited for notifications.

Contract for score recording: whoever records a score sends
``score_recorded`` with ``match=`` (a matches.Match) and, when known,
``home_score=`` / ``away_score=``. As a fallback the Match post-save
receiver also detects score fields if they are ever added to the model.

Bulk seed scripts wrap their writes in ``muted()`` so demo data notifies nobody.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import Signal, receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as date_format

from matches.models import Match
from teams.models import Roster, Team

score_recorded = Signal()
"""Sent when a score is recorded on a match.

Send with ``match=`` and optionally ``home_score=`` / ``away_score=``.
In-app only; no email is sent.
"""

MATCH_SCORE_ATTRS = ("home_score", "away_score")
MATCH_SCHEDULE_ATTRS = ("starts_at", "ends_at", "facility_id")
VERB_MAX_LENGTH = 255

# A ContextVar, so a mute in one thread or task never silences another.
_muted = ContextVar("notifications_muted", default=False)


@contextmanager
def muted():
    """Create no notifications inside this block. For seed scripts only.

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


def _display_name(user):
    return user.get_full_name() or user.username


def _team_member_ids(team):
    """Roster players plus the captain: everyone a team event reaches."""
    ids = set(Roster.objects.filter(team=team).values_list("player_id", flat=True))
    if team.captain_id:
        ids.add(team.captain_id)
    return ids


def _notify_ids(user_ids, verb, link=""):
    from .models import Notification

    if _muted.get():
        return
    recipients = {uid for uid in user_ids if uid is not None}
    if not recipients or not verb:
        return
    # Long team and facility names can pass the column limit.
    verb = verb[:VERB_MAX_LENGTH]
    Notification.objects.bulk_create(
        [Notification(recipient_id=uid, verb=verb, link=link) for uid in recipients]
    )


def _match_link(match):
    return reverse("matches:season_schedule", args=[match.season_id])


def _notify_match_teams(match, verb, link=""):
    ids = _team_member_ids(match.home_team) | _team_member_ids(match.away_team)
    _notify_ids(ids, verb, link or _match_link(match))


def _score_values(match):
    """The match's score fields, or None when the model has no such fields."""
    if not all(hasattr(match, attr) for attr in MATCH_SCORE_ATTRS):
        return None
    return tuple(getattr(match, attr) for attr in MATCH_SCORE_ATTRS)


def _score_verb(match, home_score=None, away_score=None):
    if home_score is not None and away_score is not None:
        return (
            f"Final score: {match.home_team} {home_score} – "
            f"{away_score} {match.away_team}"
        )
    return f"Score recorded: {match}"


def _rescheduled_verb(match):
    when = date_format(timezone.localtime(match.starts_at), "D M j g:i A")
    return (
        f"Match rescheduled: {match.home_team} vs {match.away_team}, "
        f"{when} at {match.facility}"
    )


def _saved_fields(update_fields):
    """Names and attnames that this save writes, or None when it writes all."""
    if update_fields is None:
        return None
    names = set(update_fields)
    return names | {f"{name}_id" for name in names}


@receiver(pre_save, sender=Match)
def match_pre_save(sender, instance, **kwargs):
    """Stash the stored row: post_save can no longer see what changed."""
    instance._pre_save_state = None
    if instance.pk is None:
        return
    attrs = MATCH_SCHEDULE_ATTRS + ("status",)
    if _score_values(instance) is not None:
        attrs += MATCH_SCORE_ATTRS
    instance._pre_save_state = (
        Match.objects.filter(pk=instance.pk).values(*attrs).first()
    )


def _changed(instance, stored, attrs, saved):
    """True when this save writes a new value for one of ``attrs``."""
    return any(
        getattr(instance, attr) != stored[attr]
        for attr in attrs
        if saved is None or attr in saved
    )


@receiver(post_save, sender=Match)
def match_saved(sender, instance, created, update_fields=None, **kwargs):
    if created:
        if instance.status != Match.Status.SCHEDULED:
            return
        _notify_match_teams(
            instance,
            f"New match scheduled: {instance.home_team} vs {instance.away_team}",
        )
        return
    stored = getattr(instance, "_pre_save_state", None)
    if stored is None:
        return
    saved = _saved_fields(update_fields)
    cancelled = Match.Status.CANCELLED
    if _changed(instance, stored, ("status",), saved) and instance.status == cancelled:
        # A cancellation replaces every other notice from the same save.
        _notify_match_teams(
            instance,
            f"Match cancelled: {instance.home_team} vs {instance.away_team}",
        )
        return
    if instance.status != cancelled and _changed(
        instance, stored, MATCH_SCHEDULE_ATTRS, saved
    ):
        _notify_match_teams(instance, _rescheduled_verb(instance))
    values = _score_values(instance)
    if values is None or not all(v is not None for v in values):
        return
    if saved is not None and not saved.intersection(MATCH_SCORE_ATTRS):
        return
    if any(stored[attr] is None for attr in MATCH_SCORE_ATTRS):
        _notify_match_teams(
            instance, _score_verb(instance, *values), _match_link(instance)
        )


@receiver(score_recorded)
def score_recorded_handler(sender, match=None, **kwargs):
    if match is None:
        return
    _notify_match_teams(
        match,
        _score_verb(match, kwargs.get("home_score"), kwargs.get("away_score")),
        _match_link(match),
    )


@receiver(post_save, sender=Roster)
def roster_entry_added(sender, instance, created, **kwargs):
    if not created:
        return
    _notify_ids(
        _team_member_ids(instance.team),
        f"{_display_name(instance.player)} joined {instance.team}",
        reverse("teams:detail", args=[instance.team_id]),
    )


@receiver(post_delete, sender=Roster)
def roster_entry_removed(sender, instance, **kwargs):
    try:
        team = instance.team
    except Team.DoesNotExist:
        # The team itself was deleted: there is no team page left to link.
        return
    ids = _team_member_ids(team) | {instance.player_id}
    _notify_ids(
        ids,
        f"{_display_name(instance.player)} left {team}",
        reverse("teams:detail", args=[team.pk]),
    )
