"""Template helpers for the design system (docs/DESIGN.md). Load with {% load ui %}."""

from django import forms, template

register = template.Library()

SPORT_ICONS = {
    "soccer": "ti-ball-football",
    "american football": "ti-ball-american-football",
    "basketball": "ti-ball-basketball",
    "volleyball": "ti-ball-volleyball",
    "tennis": "ti-ball-tennis",
}
DEFAULT_SPORT_ICON = "ti-trophy"


@register.filter
def initials(user):
    """Two-letter initials for an avatar, falling back to the email's first letter."""
    first = (user.first_name or "")[:1]
    last = (user.last_name or "")[:1]
    if first or last:
        return f"{first}{last}".upper()
    return (user.email or user.username or "?")[:1].upper()


@register.filter
def sport_icon(sport):
    return SPORT_ICONS.get((sport or "").strip().lower(), DEFAULT_SPORT_ICON)


@register.filter
def control(field):
    """Render a form field's widget with the design system's classes and error state."""
    widget = field.field.widget
    if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
        css = "form-check-input"
    elif isinstance(widget, forms.Select):
        css = "form-select"
    else:
        css = "form-control"
    if field.errors:
        css += " is-invalid"
    existing = widget.attrs.get("class")
    if existing:
        css = f"{existing} {css}"
    return field.as_widget(attrs={"class": css})
