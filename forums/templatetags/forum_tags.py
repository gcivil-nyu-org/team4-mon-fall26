from django import template
from django.utils import timezone
from django.utils.timesince import timesince

from forums.selectors import latest_topics

register = template.Library()

HOME_PANEL_SIZE = 5


def _relative_time(moment):
    """'5 minutes ago', with one unit only."""
    if (timezone.now() - moment).total_seconds() < 60:
        return "Just now"
    return f"{timesince(moment, depth=1)} ago"


@register.inclusion_tag("forums/_home_panel.html", takes_context=True)
def home_forum_panel(context):
    """Dashboard rail card: the forum topics with the newest activity.

    One query. Reported topics stay in the panel, because the forum list
    page shows them too.
    """
    user = context.get("user")
    if not getattr(user, "is_authenticated", False):
        return {"show": False}
    topics = list(latest_topics(limit=HOME_PANEL_SIZE))
    for topic in topics:
        topic.time_label = _relative_time(topic.last_activity_at)
    return {"show": True, "topics": topics}
