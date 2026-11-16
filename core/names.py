"""The one display name for a person. Never an email address.

Templates use it as the ``display_name`` filter (``{% load ui %}``).
"""

FALLBACK_NAME = "PlayNYU player"


def display_name(user):
    """Full name, else the fallback. ``None`` falls back."""
    if user is None:
        return FALLBACK_NAME
    return (user.get_full_name() or "").strip() or FALLBACK_NAME
