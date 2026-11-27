from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag
def profile_url(user):
    """Link to a player's profile page."""
    return reverse("profiles:detail", args=[user.pk])
