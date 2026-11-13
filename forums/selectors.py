"""Read queries for the forum, shared by its pages and by other apps."""

from django.db.models import Count

from .models import Topic


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
