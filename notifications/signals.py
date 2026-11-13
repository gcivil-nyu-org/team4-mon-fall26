"""Receivers that create notifications.

All receivers live in this app (connected on import from apps.ready), so
matches/, teams/ and core/ are never edited for notifications.

Contract for score recording: whoever records a score sends
``score_recorded`` with ``match=`` (a matches.Match) and, when known,
``home_score=`` / ``away_score=``. As a fallback the Match post-save
receiver also detects score fields if they are ever added to the model.
"""

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import Signal, receiver
from django.urls import reverse

from matches.models import Match
from teams.models import Roster, Team

score_recorded = Signal()
"""Sent when a score is recorded on a match.

Send with ``match=`` and optionally ``home_score=`` / ``away_score=``.
In-app only; no email is sent.
"""

MATCH_SCORE_ATTRS = ("home_score", "away_score")


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

    recipients = {uid for uid in user_ids if uid is not None}
    if not recipients or not verb:
        return
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


@receiver(pre_save, sender=Match)
def match_pre_save(sender, instance, **kwargs):
    """Stash the stored scores: post_save can no longer see what changed."""
    if instance.pk is None or _score_values(instance) is None:
        return
    stored = Match.objects.filter(pk=instance.pk).values(*MATCH_SCORE_ATTRS).first()
    if stored is None:
        return
    instance._pre_save_scores = tuple(stored[attr] for attr in MATCH_SCORE_ATTRS)


@receiver(post_save, sender=Match)
def match_saved(sender, instance, created, **kwargs):
    if created:
        if instance.status != Match.Status.SCHEDULED:
            return
        _notify_match_teams(
            instance,
            f"New match scheduled: {instance.home_team} vs {instance.away_team}",
        )
        return
    values = _score_values(instance)
    if values is None or not all(v is not None for v in values):
        return
    previous = getattr(instance, "_pre_save_scores", (None, None))
    if any(v is None for v in previous):
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
