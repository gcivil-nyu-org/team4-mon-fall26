"""Map pins for facilities, as static/js/facility_map.js reads them."""

from django.urls import reverse


def map_marker(facility):
    """{name, lat, lng, url} for a facility with coordinates."""
    return {
        "name": facility.name,
        "lat": float(facility.latitude),
        "lng": float(facility.longitude),
        "url": reverse("facilities:detail", args=[facility.pk]),
    }
