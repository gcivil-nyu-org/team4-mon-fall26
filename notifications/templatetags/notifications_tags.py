from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def unread_notifications_count(context):
    """Unread in-app notifications for the navbar bell (0 when logged out)."""
    user = context.get("user")
    if not getattr(user, "is_authenticated", False):
        return 0
    return user.notifications.filter(is_read=False).count()
