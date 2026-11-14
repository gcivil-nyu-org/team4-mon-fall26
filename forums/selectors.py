"""Read queries for the forum, shared by its pages and by other apps."""

from django.db.models import Count

from .models import Reply, Topic


def topics_with_reply_counts():
    """All topics, newest activity first, each with `reply_count`."""
    return (
        Topic.objects.select_related("author", "sport")
        .annotate(reply_count=Count("replies"))
        .order_by("-last_activity_at", "-pk")
    )


def latest_topics(limit=5):
    """The `limit` most recently active topics, each with `reply_count`."""
    return topics_with_reply_counts()[:limit]


def flagged_topics():
    """Reported topics for the moderation queue, newest first."""
    return (
        Topic.objects.filter(is_flagged=True)
        .select_related("author", "sport")
        .order_by("-created_at", "-pk")
    )


def flagged_replies():
    """Reported replies for the moderation queue, newest first."""
    return (
        Reply.objects.filter(is_flagged=True)
        .select_related("author", "topic", "topic__sport")
        .order_by("-created_at", "-pk")
    )
