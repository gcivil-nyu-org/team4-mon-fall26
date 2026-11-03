from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

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
