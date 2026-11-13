from django import template

from accounts.roles import SCOREKEEPER_ROLE, has_role
from matches.scorekeeping import group_assigned_matches

register = template.Library()

CARD_MATCHES = 3


@register.inclusion_tag("matches/_matches_to_score.html", takes_context=True)
def matches_to_score(context):
    """Dashboard rail card. Renders nothing for users who aren't scorekeepers."""
    user = context.get("user")
    if not has_role(user, SCOREKEEPER_ROLE):
        return {"show": False}
    waiting = group_assigned_matches(user)["needs_score"]
    return {
        "show": True,
        "count": len(waiting),
        "matches": waiting[:CARD_MATCHES],
    }
