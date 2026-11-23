"""The roles page (#261). The rules live in accounts/role_admin.py."""

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.names import display_name

from . import role_admin
from .forms import RoleFilterForm
from .roles import SCOREKEEPER_ROLE

ROLES_PER_PAGE = 20


@login_required
def role_list(request):
    """League Admins and superusers see who holds each staff role."""
    if not role_admin.can_manage_roles(request.user):
        raise PermissionDenied
    form = RoleFilterForm(request.GET)
    rows = form.filter(role_admin.role_rows())
    page_obj = Paginator(rows, ROLES_PER_PAGE).get_page(request.GET.get("page"))
    filters = form.cleaned()
    return render(
        request,
        "accounts/roles.html",
        {
            "filter_form": form,
            "filters": filters,
            "page_obj": page_obj,
            # Built from the cleaned values, so a bad value drops out of the links.
            "querystring": urlencode(filters),
            "league_admin_count": role_admin.league_admin_count(),
            "nav_section": "league_setup",
        },
    )


def _role_label(role_name):
    return "a Scorekeeper" if role_name == SCOREKEEPER_ROLE else "a League Admin"


def _back_to_list(post):
    """The list URL with the same valid filters and page, in the order q, role, page."""
    params = RoleFilterForm(
        {"q": post.get("q", ""), "role": post.get("role_filter", "")}
    ).cleaned()
    page = post.get("page", "")
    if page.isdecimal():
        params["page"] = page
    url = reverse("accounts:roles")
    return f"{url}?{urlencode(params)}" if params else url


@login_required
@require_POST
def change_role(request, user_pk):
    """Grant or remove one role, then go back to the same list page."""
    if not role_admin.can_manage_roles(request.user):
        raise PermissionDenied
    target = get_object_or_404(role_admin.listable_users(), pk=user_pk)
    role_name = role_admin.MANAGED_ROLES.get(request.POST.get("role"))
    action = request.POST.get("action")
    if role_name is None or action not in ("add", "remove"):
        return HttpResponseBadRequest("Unknown role or action.")
    grant = action == "add"
    name = display_name(target)
    label = _role_label(role_name)
    try:
        changed = role_admin.change_role(request.user, target, role_name, grant)
    except role_admin.RoleChangeRefused as error:
        messages.error(request, str(error))
        return redirect(_back_to_list(request.POST))

    if not changed:
        held = f"is already {label}" if grant else f"isn't {label}"
        messages.info(request, f"{name} {held}.")
    elif grant:
        messages.success(request, f"{name} is now {label}.")
    else:
        messages.success(request, f"{name} is no longer {label}.")
        if role_name == SCOREKEEPER_ROLE:
            unscored = role_admin.unscored_match_count(target)
            if unscored:
                matches = "match" if unscored == 1 else "matches"
                messages.warning(
                    request,
                    f"{name} still has {unscored} unscored {matches} and can't "
                    "score them now. Choose another scorekeeper on Manage matches.",
                )
    return redirect(_back_to_list(request.POST))
