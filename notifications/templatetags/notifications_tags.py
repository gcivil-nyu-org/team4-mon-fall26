from django import template

register = template.Library()

HOME_PANEL_SIZE = 5


@register.simple_tag(takes_context=True)
def unread_notifications_count(context):
    """Unread in-app notifications for the navbar bell (0 when logged out)."""
    user = context.get("user")
    if not getattr(user, "is_authenticated", False):
        return 0
    return user.notifications.filter(is_read=False).count()


def notification_url(notification):
    """Where a notification row goes. The one place to change the target."""
    return notification.link


@register.inclusion_tag("notifications/_home_panel.html", takes_context=True)
def home_activity_panel(context):
    """Dashboard rail card: the user's latest notifications, newest first."""
    user = context.get("user")
    if not getattr(user, "is_authenticated", False):
        return {"show": False}
    notifications = list(
        user.notifications.order_by("-created_at", "-pk")[:HOME_PANEL_SIZE]
    )
    for notification in notifications:
        notification.url = notification_url(notification)
    return {"show": True, "notifications": notifications}
