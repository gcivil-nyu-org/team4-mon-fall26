from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.roles import LEAGUE_ADMIN_ROLE, assign_role
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


class ManageFacilityTestData(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.player = User.objects.create_user(
            username="player", email="player@nyu.edu", password="pass12345!"
        )
        cls.admin = User.objects.create_user(
            username="admin", email="admin@nyu.edu", password="pass12345!"
        )
        assign_role(cls.admin, LEAGUE_ADMIN_ROLE)
        cls.root = User.objects.create_superuser(
            username="root", email="root@nyu.edu", password="pass12345!"
        )
        cls.nyu = Facility.objects.create(
            name="Palladium", address="140 E 14th St", source=Facility.Source.NYU
        )
        cls.city = Facility.objects.create(
            name="Pier 40",
            address="353 West St",
            source=Facility.Source.CITY,
            external_id="M123",
        )
        cls.manage_url = reverse("facilities:manage")
        cls.create_url = reverse("facilities:create")
        cls.edit_url = reverse("facilities:edit", args=[cls.nyu.pk])
        cls.city_edit_url = reverse("facilities:edit", args=[cls.city.pk])


class ManageFacilityPermissionTests(ManageFacilityTestData):
    def urls(self):
        return (self.manage_url, self.create_url, self.edit_url, self.city_edit_url)

    def test_anonymous_user_is_redirected_to_login(self):
        for url in self.urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_player_is_forbidden(self):
        self.client.force_login(self.player)
        for url in self.urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_player_cannot_submit(self):
        self.client.force_login(self.player)
        for url in (self.create_url, self.edit_url):
            with self.subTest(url=url):
                response = self.client.post(url, {"name": "Hacked", "is_active": "on"})
                self.assertEqual(response.status_code, 403)
        self.assertEqual(Facility.objects.count(), 2)
        self.nyu.refresh_from_db()
        self.assertEqual(self.nyu.name, "Palladium")

    def test_league_admin_and_superuser_can_open_pages(self):
        for user in (self.admin, self.root):
            self.client.force_login(user)
            for url in (self.manage_url, self.create_url, self.edit_url):
                with self.subTest(user=user.username, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertTemplateUsed(response, "base.html")


class ManageFacilityPageTests(ManageFacilityTestData):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_lists_every_facility_with_nyu_first_and_edit_links_only_on_nyu(self):
        hidden = Facility.objects.create(
            name="Zeta gym", source=Facility.Source.NYU, is_active=False
        )
        response = self.client.get(self.manage_url)
        self.assertEqual(
            list(response.context["facilities"]), [self.nyu, hidden, self.city]
        )
        self.assertContains(response, f'href="{self.edit_url}"')
        self.assertContains(
            response, f'href="{reverse("facilities:edit", args=[hidden.pk])}"'
        )
        self.assertNotContains(response, f'href="{self.city_edit_url}"')
        self.assertContains(response, "Inactive")

    def test_empty_state(self):
        Facility.objects.all().delete()
        self.assertContains(self.client.get(self.manage_url), "No facilities yet")

    def test_marks_league_setup_as_the_current_nav_item(self):
        response = self.client.get(self.manage_url)
        self.assertContains(
            response,
            f'<a class="nav-link" href="{reverse("teams:league_setup")}"'
            ' aria-current="page">',
        )
        self.assertNotContains(
            response,
            f'<a class="nav-link" href="{reverse("facilities:map")}"'
            ' aria-current="page">',
        )

    def test_add_creates_an_nyu_facility(self):
        soccer = Sport.objects.create(name="Soccer")
        response = self.client.post(
            self.create_url,
            {
                "name": "  Coles   Center ",
                "address": " 181 Mercer  St ",
                "borough": Facility.Borough.MANHATTAN,
                "latitude": "40.727000",
                "longitude": "-73.997000",
                "sports": [soccer.pk],
                "is_active": "on",
                # Not form fields, so these must be ignored.
                "source": Facility.Source.CITY,
                "external_id": "M999",
            },
        )
        self.assertRedirects(response, self.manage_url)
        facility = Facility.objects.get(name="Coles Center")
        self.assertEqual(facility.address, "181 Mercer St")
        self.assertEqual(facility.source, Facility.Source.NYU)
        self.assertEqual(facility.external_id, "")
        self.assertTrue(facility.has_location)
        self.assertEqual(list(facility.sports.all()), [soccer])

    def test_add_can_leave_everything_but_the_name_empty(self):
        response = self.client.post(self.create_url, {"name": "Coles"})
        self.assertRedirects(response, self.manage_url)
        self.assertFalse(Facility.objects.get(name="Coles").is_active)

    def test_name_is_required_with_one_error(self):
        for name in ("", "   "):
            with self.subTest(name=name):
                response = self.client.post(self.create_url, {"name": name})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context["form"].errors["name"]), 1)
        self.assertEqual(Facility.objects.count(), 2)

    def test_same_name_and_address_are_rejected_ignoring_case_and_spacing(self):
        response = self.client.post(
            self.create_url, {"name": " PALLADIUM ", "address": "140  e 14TH st"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("already exists", response.context["form"].errors["name"][0])
        self.assertEqual(Facility.objects.count(), 2)

    def test_duplicates_of_city_and_inactive_facilities_are_rejected(self):
        hidden = Facility.objects.create(
            name="Old gym", source=Facility.Source.NYU, is_active=False
        )
        for other in (self.city, hidden):
            with self.subTest(facility=other.name):
                response = self.client.post(
                    self.create_url, {"name": other.name, "address": other.address}
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("name", response.context["form"].errors)

    def test_blank_addresses_collide_on_name_alone(self):
        Facility.objects.create(name="Coles", source=Facility.Source.NYU)
        response = self.client.post(self.create_url, {"name": "coles"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.context["form"].errors)

    def test_same_name_at_another_address_is_allowed(self):
        response = self.client.post(
            self.create_url, {"name": "Palladium", "address": "1 Other St"}
        )
        self.assertRedirects(response, self.manage_url)

    def test_coordinates_must_be_a_pair_and_in_range(self):
        for data, field in (
            ({"latitude": "40.7"}, None),
            ({"latitude": "91", "longitude": "0"}, "latitude"),
            ({"latitude": "0", "longitude": "181"}, "longitude"),
        ):
            with self.subTest(data=data):
                response = self.client.post(self.create_url, {"name": "Field", **data})
                self.assertEqual(response.status_code, 200)
                form = response.context["form"]
                if field:
                    self.assertIn(field, form.errors)
                else:
                    self.assertEqual(len(form.non_field_errors()), 1)
        self.assertFalse(Facility.objects.filter(name="Field").exists())

    def test_edit_saves_changes(self):
        response = self.client.post(
            self.edit_url, {"name": "Palladium Gym", "address": "140 E 14th St"}
        )
        self.assertRedirects(response, self.manage_url)
        self.nyu.refresh_from_db()
        self.assertEqual(self.nyu.name, "Palladium Gym")
        self.assertFalse(self.nyu.is_active)
        self.assertEqual(self.nyu.source, Facility.Source.NYU)

    def test_edit_form_starts_with_the_saved_values(self):
        response = self.client.get(self.edit_url)
        self.assertContains(response, 'value="Palladium"')
        self.assertContains(response, 'value="140 E 14th St"')

    def test_edit_can_keep_or_recase_its_own_name_and_address(self):
        response = self.client.post(
            self.edit_url, {"name": "PALLADIUM", "address": "140 e 14th st"}
        )
        self.assertRedirects(response, self.manage_url)
        self.nyu.refresh_from_db()
        self.assertEqual(self.nyu.name, "PALLADIUM")

    def test_edit_cannot_collide_with_another_facility(self):
        for other in (
            self.city,
            Facility.objects.create(
                name="Coles", address="181 Mercer St", source=Facility.Source.NYU
            ),
        ):
            with self.subTest(facility=other.name):
                response = self.client.post(
                    self.edit_url,
                    {"name": other.name.upper(), "address": other.address},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("name", response.context["form"].errors)
                # The page header still shows the saved name.
                self.assertContains(response, "<h1>Edit Palladium</h1>", html=True)
        self.nyu.refresh_from_db()
        self.assertEqual(self.nyu.name, "Palladium")

    def test_city_facilities_cannot_be_edited(self):
        self.assertEqual(self.client.get(self.city_edit_url).status_code, 404)
        response = self.client.post(self.city_edit_url, {"name": "Renamed"})
        self.assertEqual(response.status_code, 404)
        self.city.refresh_from_db()
        self.assertEqual(self.city.name, "Pier 40")
        self.assertEqual(self.city.source, Facility.Source.CITY)
