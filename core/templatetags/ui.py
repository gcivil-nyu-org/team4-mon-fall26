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


PLAYER_NAME_FALLBACK = "PlayNYU player"


@register.filter
def initials(user):
    """Two-letter initials for an avatar. Never the email.

    A person with no name gets "P", for "PlayNYU player".
    """
    first = (getattr(user, "first_name", "") or "")[:1]
    last = (getattr(user, "last_name", "") or "")[:1]
    if first or last:
        return f"{first}{last}".upper()
    return PLAYER_NAME_FALLBACK[:1]


@register.filter
def display_name(user):
    """A player's full name for pages anyone can see. Never the email."""
    if user is None:
        return PLAYER_NAME_FALLBACK
    return user.get_full_name() or PLAYER_NAME_FALLBACK


@register.filter
def ordinal(n):
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, 22nd, 101st, 111th."""
    number = int(n)
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


@register.filter
def player_name(user):
    """A player's full name for pages any member can see. Never the email."""
    if user is None:
        return PLAYER_NAME_FALLBACK
    return user.get_full_name() or PLAYER_NAME_FALLBACK


@register.filter
def sport_icon(sport):
    if sport is None:
        return DEFAULT_SPORT_ICON

    # Support both Sport model objects and legacy strings.
    sport_name = getattr(sport, "name", sport)

    return SPORT_ICONS.get(
        str(sport_name).strip().lower(),
        DEFAULT_SPORT_ICON,
    )


@register.filter
def control(field, extra=""):
    """Render a form field's widget with the design system's classes and error state.

    `extra` adds classes, for example {{ field|control:"form-control-sm pn-num" }}.
    """
    widget = field.field.widget
    if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
        css = "form-check-input"
    elif isinstance(widget, forms.Select):
        css = "form-select"
    else:
        css = "form-control"
    if extra:
        css += f" {extra}"
    if field.errors:
        css += " is-invalid"
    existing = widget.attrs.get("class")
    if existing:
        css = f"{existing} {css}"
    return field.as_widget(attrs={"class": css})
