from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from teams.models import Sport

from .models import Facility


class FacilityModelTests(TestCase):
    def test_nyu_facility_normalizes_name_and_address(self):
        facility = Facility.objects.create(
            name="  Palladium   Athletic  Facility ",
            address=" 140 E  14th St ",
            source=Facility.Source.NYU,
        )
        self.assertEqual(facility.name, "Palladium Athletic Facility")
        self.assertEqual(facility.address, "140 E 14th St")
        self.assertEqual(str(facility), "Palladium Athletic Facility")
        self.assertTrue(facility.is_active)
        self.assertFalse(facility.has_location)

    def test_name_is_required(self):
        with self.assertRaises(ValidationError) as ctx:
            Facility.objects.create(name="   ", source=Facility.Source.NYU)
        self.assertIn("name", ctx.exception.message_dict)

    def test_city_facility_needs_external_id(self):
        with self.assertRaises(ValidationError) as ctx:
            Facility.objects.create(name="Pier 40", source=Facility.Source.CITY)
        self.assertIn("external_id", ctx.exception.message_dict)

    def test_latitude_and_longitude_go_together(self):
        with self.assertRaises(ValidationError):
            Facility.objects.create(
                name="Field", source=Facility.Source.NYU, latitude=Decimal("40.7")
            )
        facility = Facility.objects.create(
            name="Field",
            source=Facility.Source.NYU,
            latitude=Decimal("40.729500"),
            longitude=Decimal("-73.996500"),
        )
        self.assertTrue(facility.has_location)

    def test_external_id_unique_per_source(self):
        Facility.objects.create(
            name="Pier 40", source=Facility.Source.CITY, external_id="M123"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Facility.objects.create(
                name="Pier 40 again", source=Facility.Source.CITY, external_id="M123"
            )

    def test_nyu_facilities_can_share_blank_external_id(self):
        Facility.objects.create(name="Palladium", source=Facility.Source.NYU)
        Facility.objects.create(name="Coles", source=Facility.Source.NYU)
        self.assertEqual(Facility.objects.count(), 2)

    def test_coordinates_out_of_range_are_rejected_by_the_database(self):
        facility = Facility.objects.create(name="Field", source=Facility.Source.NYU)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Facility.objects.filter(pk=facility.pk).update(
                latitude=Decimal("91"), longitude=Decimal("0")
            )

    def test_sports_and_ordering(self):
        soccer = Sport.objects.create(name="Soccer")
        b = Facility.objects.create(name="B field", source=Facility.Source.NYU)
        a = Facility.objects.create(name="A field", source=Facility.Source.NYU)
        a.sports.add(soccer)
        self.assertEqual(list(Facility.objects.all()), [a, b])
        self.assertEqual(list(soccer.facilities.all()), [a])

    def test_registered_in_admin(self):
        self.assertTrue(admin.site.is_registered(Facility))


class FacilityPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="player", email="player@nyu.edu", password="pass12345!"
        )
        cls.pinned = Facility.objects.create(
            name="Pier 40",
            address="353 West St",
            borough=Facility.Borough.MANHATTAN,
            source=Facility.Source.NYU,
            latitude=Decimal("40.729500"),
            longitude=Decimal("-74.011000"),
        )
        cls.unpinned = Facility.objects.create(name="Coles", source=Facility.Source.NYU)
        cls.hidden = Facility.objects.create(
            name="Old gym",
            source=Facility.Source.NYU,
            is_active=False,
            latitude=Decimal("40.7"),
            longitude=Decimal("-74"),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_pages_require_login(self):
        self.client.logout()
        for url in (
            reverse("facilities:map"),
            reverse("facilities:detail", args=[self.pinned.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_map_pins_active_facilities_with_coordinates(self):
        response = self.client.get(reverse("facilities:map"))
        self.assertEqual(
            response.context["markers"],
            [
                {
                    "name": "Pier 40",
                    "lat": 40.7295,
                    "lng": -74.011,
                    "url": reverse("facilities:detail", args=[self.pinned.pk]),
                }
            ],
        )
        self.assertContains(response, 'id="pn-map"')
        self.assertContains(response, "leaflet@1.9.4/dist/leaflet.js")
        self.assertContains(response, "leaflet@1.9.4/dist/leaflet.css")

    def test_text_list_includes_facilities_without_coordinates(self):
        response = self.client.get(reverse("facilities:map"))
        self.assertContains(response, "Coles")
        self.assertNotContains(response, "Old gym")

    def test_empty_state_has_no_map_or_leaflet(self):
        Facility.objects.all().delete()
        response = self.client.get(reverse("facilities:map"))
        self.assertContains(response, "No facilities yet")
        self.assertNotContains(response, 'id="pn-map"')
        self.assertNotContains(response, "leaflet.js")
        self.assertNotContains(response, "leaflet.css")
        self.assertNotContains(response, "Select a pin")

    def test_facility_names_are_escaped_in_map_data(self):
        Facility.objects.create(
            name="</script><script>alert(1)</script>",
            source=Facility.Source.NYU,
            latitude=Decimal("40.7"),
            longitude=Decimal("-74"),
        )
        response = self.client.get(reverse("facilities:map"))
        self.assertNotContains(response, "<script>alert(1)")

    def test_detail_with_and_without_coordinates(self):
        response = self.client.get(reverse("facilities:detail", args=[self.pinned.pk]))
        self.assertContains(response, "353 West St, Manhattan")
        self.assertContains(response, 'id="pn-map"')
        response = self.client.get(
            reverse("facilities:detail", args=[self.unpinned.pk])
        )
        self.assertContains(response, "No map location yet")
        self.assertNotContains(response, 'id="pn-map"')

    def test_detail_shows_borough_without_an_address(self):
        facility = Facility.objects.create(
            name="Riverside Field",
            borough=Facility.Borough.BRONX,
            source=Facility.Source.NYU,
        )
        response = self.client.get(reverse("facilities:detail", args=[facility.pk]))
        self.assertContains(response, '<div class="page-meta">Bronx</div>')

    def test_inactive_facility_detail_is_404(self):
        response = self.client.get(reverse("facilities:detail", args=[self.hidden.pk]))
        self.assertEqual(response.status_code, 404)

    def test_nav_links_to_facilities(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, reverse("facilities:map"))
