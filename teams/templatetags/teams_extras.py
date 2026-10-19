from django import template
from django.urls import NoReverseMatch, reverse

register = template.Library()


@register.simple_tag
def profile_url(user):
    """Link to a player's profile. Falls back to '#' until the profile page (T11) exists."""
    try:
        return reverse("profiles:detail", args=[user.pk])
    except NoReverseMatch:
        return "#"
