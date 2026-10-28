from django import template

from accounts.roles import has_role

register = template.Library()


@register.filter
def has_account_role(user, role_name):
    return has_role(user, role_name)
