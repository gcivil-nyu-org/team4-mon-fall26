from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from teams.views import _require_league_admin

from .forms import NYUFacilityForm
from .models import Facility


def _map_marker(facility):
    return {
        "name": facility.name,
        "lat": float(facility.latitude),
        "lng": float(facility.longitude),
        "url": reverse("facilities:detail", args=[facility.pk]),
    }


@login_required
def facility_map(request):
    """Every active facility: pins for those with coordinates, plus a text list."""
    facilities = Facility.objects.filter(is_active=True).prefetch_related("sports")
    markers = [_map_marker(f) for f in facilities if f.has_location]
    return render(
        request,
        "facilities/facility_map.html",
        {"facilities": facilities, "markers": markers},
    )


@login_required
def facility_detail(request, pk):
    facility = get_object_or_404(
        Facility.objects.prefetch_related("sports"), pk=pk, is_active=True
    )
    markers = [_map_marker(facility)] if facility.has_location else []
    return render(
        request,
        "facilities/facility_detail.html",
        {"facility": facility, "markers": markers},
    )


@login_required
def manage_facilities(request):
    """League Admin list of every facility, with the editable NYU ones first."""
    _require_league_admin(request.user)
    return render(
        request,
        "facilities/manage_facilities.html",
        {
            "facilities": Facility.objects.order_by("-source", "name", "pk"),
            "nav_section": "league_setup",
        },
    )


@login_required
def facility_form(request, pk=None):
    """Add an NYU facility, or edit one. City facilities aren't editable here."""
    _require_league_admin(request.user)
    facility = (
        get_object_or_404(Facility, pk=pk, source=Facility.Source.NYU) if pk else None
    )
    form = NYUFacilityForm(request.POST or None, instance=facility)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        verb = "Saved" if facility else "Added"
        messages.success(request, f"{verb} {saved}.")
        return redirect("facilities:manage")
    return render(
        request,
        "facilities/facility_form.html",
        {"form": form, "facility": facility, "nav_section": "league_setup"},
    )
