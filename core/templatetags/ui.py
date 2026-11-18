"""Template helpers for the design system (docs/DESIGN.md). Load with {% load ui %}."""

from django import forms, template

from core import names

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
    """Two-letter initials for an avatar. Never the email.

    A person with no name gets "P", for "PlayNYU player".
    """
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    letters = f"{first_name[:1]}{last_name[:1]}".upper()
    if letters:
        return letters
    return names.FALLBACK_NAME[:1]


# The one display-name filter: full name or "PlayNYU player", never the email.
display_name = register.filter("display_name", names.display_name)


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
def sport_icon(sport):
    """Tabler icon for a Sport, or for a sport name string."""
    if sport is None:
        return DEFAULT_SPORT_ICON
    # Sport.name, or the string itself for older callers.
    sport_name = getattr(sport, "name", sport)
    key = str(sport_name).strip().lower()
    return SPORT_ICONS.get(key, DEFAULT_SPORT_ICON)


@register.filter
def control(field, extra=""):
    """Render a form field's widget with the design system's classes and error state.

    `extra` adds classes, for example {{ field|control:"form-control-sm pn-num" }}.
    """
    widget = field.field.widget
    if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
        css_class = "form-check-input"
    elif isinstance(widget, forms.Select):
        css_class = "form-select"
    else:
        css_class = "form-control"

    classes = []
    existing = widget.attrs.get("class")
    if existing:
        classes.append(existing)
    classes.append(css_class)
    if extra:
        classes.append(extra)
    if field.errors:
        classes.append("is-invalid")
    return field.as_widget(attrs={"class": " ".join(classes)})
