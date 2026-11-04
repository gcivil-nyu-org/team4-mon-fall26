from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

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
