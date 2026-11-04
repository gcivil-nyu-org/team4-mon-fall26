import json
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from teams.models import Sport

from .management.commands.import_facilities import COLUMN_MAP
from .models import Facility

TESTDATA = Path(__file__).parent / "testdata"
CSV_FILE = TESTDATA / "athletic_facilities.csv"
UPDATED_CSV_FILE = TESTDATA / "athletic_facilities_updated.csv"
GEOJSON_FILE = TESTDATA / "athletic_facilities.geojson"


def run_import(path):
    """Run the command and return its (stdout, stderr)."""
    stdout, stderr = StringIO(), StringIO()
    call_command("import_facilities", str(path), stdout=stdout, stderr=stderr)
    return stdout.getvalue(), stderr.getvalue()


class ImportFacilitiesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.soccer = Sport.objects.create(name="Soccer")
        cls.basketball = Sport.objects.create(name="Basketball")
        cls.tennis = Sport.objects.create(name="Tennis")

    def write_file(self, name, content):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / name
        path.write_bytes(content)
        return path


class CsvImportTests(ImportFacilitiesTestCase):
    def test_creates_facilities_with_mapped_fields(self):
        stdout, _ = run_import(CSV_FILE)

        self.assertIn("created: 3, updated: 0, skipped: 6, unchanged: 0", stdout)
        pier = Facility.objects.get(external_id="M100")
        self.assertEqual(pier.source, Facility.Source.CITY)
        self.assertEqual(pier.name, "Pier 40 Field")
        self.assertEqual(pier.address, "353 West St")
        self.assertEqual(pier.borough, Facility.Borough.MANHATTAN)
        self.assertEqual(pier.latitude, Decimal("40.729500"))
        self.assertEqual(pier.longitude, Decimal("-74.011000"))
        self.assertTrue(pier.is_active)

    def test_reads_coordinates_from_wkt_when_columns_are_empty(self):
        run_import(CSV_FILE)
        courts = Facility.objects.get(external_id="B200")
        self.assertEqual(courts.latitude, Decimal("40.720000"))
        self.assertEqual(courts.longitude, Decimal("-73.951000"))

    def test_rerun_creates_no_duplicates_and_changes_nothing(self):
        run_import(CSV_FILE)
        before = list(Facility.objects.values())

        stdout, _ = run_import(CSV_FILE)

        self.assertIn("created: 0, updated: 0, skipped: 6, unchanged: 3", stdout)
        self.assertEqual(list(Facility.objects.values()), before)

    def test_rerun_updates_changed_fields_and_sports(self):
        run_import(CSV_FILE)
        pier_pk = Facility.objects.get(external_id="M100").pk

        stdout, _ = run_import(UPDATED_CSV_FILE)

        self.assertIn("created: 0, updated: 1, skipped: 0, unchanged: 1", stdout)
        pier = Facility.objects.get(external_id="M100")
        self.assertEqual(pier.pk, pier_pk)
        self.assertEqual(pier.name, "Pier 40 Turf Field")
        self.assertEqual(list(pier.sports.all()), [self.tennis])
        self.assertEqual(Facility.objects.count(), 3)

    def test_update_keeps_is_active(self):
        run_import(CSV_FILE)
        Facility.objects.filter(external_id="M100").update(is_active=False)
        run_import(UPDATED_CSV_FILE)
        self.assertFalse(Facility.objects.get(external_id="M100").is_active)

    def test_skipped_rows_are_counted_and_explained(self):
        stdout, stderr = run_import(CSV_FILE)

        self.assertIn("skipped: 6", stdout)
        self.assertEqual(Facility.objects.count(), 3)
        self.assertIn(f"Row 4 skipped: no {COLUMN_MAP['external_id']} value", stderr)
        self.assertIn(f"Row 5 skipped: no {COLUMN_MAP['name']} value", stderr)
        self.assertIn("Row 9 skipped: M100 is repeated in this file", stderr)

    def test_invalid_rows_do_not_stop_the_import(self):
        run_import(CSV_FILE)
        for external_id in ("R500", "M600", "M700"):
            self.assertFalse(Facility.objects.filter(external_id=external_id).exists())

    def test_repeated_id_keeps_the_first_row(self):
        run_import(CSV_FILE)
        pier = Facility.objects.get(external_id="M100")
        self.assertEqual(pier.name, "Pier 40 Field")
        self.assertEqual(list(pier.sports.all()), [self.soccer])

    def test_invalid_row_leaves_the_existing_facility_alone(self):
        run_import(CSV_FILE)
        path = self.write_file(
            "bad.csv", b"SYSTEM,NAME,LAT,LON\nM100,Renamed,95.000000,-74.000000\n"
        )

        stdout, _ = run_import(path)

        self.assertIn("created: 0, updated: 0, skipped: 1, unchanged: 0", stdout)
        self.assertEqual(Facility.objects.get(external_id="M100").name, "Pier 40 Field")

    def test_rounds_extra_coordinate_precision(self):
        path = self.write_file(
            "precise.csv", b"SYSTEM,NAME,LAT,LON\nM1,Field,40.72950049,-74.01100051\n"
        )
        run_import(path)
        stdout, _ = run_import(path)

        self.assertIn("unchanged: 1", stdout)
        facility = Facility.objects.get(external_id="M1")
        self.assertEqual(facility.latitude, Decimal("40.729500"))
        self.assertEqual(facility.longitude, Decimal("-74.011001"))

    def test_reads_file_with_byte_order_mark_and_uneven_rows(self):
        path = self.write_file(
            "bom.csv", b"\xef\xbb\xbfSYSTEM,NAME\nM1,Field,surplus\nM2\n"
        )
        stdout, _ = run_import(path)
        self.assertIn("created: 1, updated: 0, skipped: 1, unchanged: 0", stdout)


class SportLinkTests(ImportFacilitiesTestCase):
    def test_links_existing_sports_only(self):
        sports_before = Sport.objects.count()

        run_import(CSV_FILE)

        courts = Facility.objects.get(external_id="B200")
        self.assertCountEqual(courts.sports.all(), [self.basketball, self.tennis])
        self.assertEqual(Sport.objects.count(), sports_before)

    def test_mapped_sport_without_a_row_is_not_created(self):
        self.soccer.delete()

        stdout, _ = run_import(CSV_FILE)

        self.assertFalse(Sport.objects.filter(name="Soccer").exists())
        self.assertFalse(Facility.objects.get(external_id="M100").sports.exists())
        self.assertIn("Soccer", stdout)

    def test_unmapped_values_are_listed(self):
        stdout, _ = run_import(CSV_FILE)
        self.assertIn("Sport values not linked: Cricket, Pickleball", stdout)
        self.assertFalse(Facility.objects.get(external_id="Q300").sports.exists())


class SourceIsolationTests(ImportFacilitiesTestCase):
    def test_nyu_rows_are_not_touched(self):
        nyu = Facility.objects.create(
            name="Palladium",
            address="140 E 14th St",
            source=Facility.Source.NYU,
            external_id="M100",
        )
        nyu.sports.add(self.basketball)

        run_import(CSV_FILE)
        run_import(UPDATED_CSV_FILE)

        nyu.refresh_from_db()
        self.assertEqual(nyu.name, "Palladium")
        self.assertEqual(nyu.address, "140 E 14th St")
        self.assertEqual(nyu.borough, "")
        self.assertEqual(list(nyu.sports.all()), [self.basketball])
        self.assertTrue(
            Facility.objects.filter(
                source=Facility.Source.CITY, external_id="M100"
            ).exists()
        )


class GeoJsonImportTests(ImportFacilitiesTestCase):
    def test_creates_facilities_and_skips_bad_features(self):
        stdout, _ = run_import(GEOJSON_FILE)

        self.assertIn("created: 3, updated: 0, skipped: 3, unchanged: 0", stdout)
        pier = Facility.objects.get(external_id="M100")
        self.assertEqual(pier.borough, Facility.Borough.MANHATTAN)
        self.assertEqual(pier.latitude, Decimal("40.729500"))
        self.assertEqual(pier.longitude, Decimal("-74.011000"))
        self.assertEqual(list(pier.sports.all()), [self.soccer])

    def test_rerun_is_idempotent(self):
        run_import(GEOJSON_FILE)
        stdout, _ = run_import(GEOJSON_FILE)
        self.assertIn("created: 0, updated: 0, skipped: 3, unchanged: 3", stdout)
        self.assertEqual(Facility.objects.count(), 3)

    def test_polygon_uses_the_middle_of_its_bounding_box(self):
        run_import(GEOJSON_FILE)
        courts = Facility.objects.get(external_id="B200")
        self.assertEqual(courts.latitude, Decimal("40.720000"))
        self.assertEqual(courts.longitude, Decimal("-73.950000"))

    def test_unknown_borough_is_left_blank(self):
        run_import(GEOJSON_FILE)
        self.assertEqual(Facility.objects.get(external_id="B200").borough, "")

    def test_missing_geometry_leaves_no_location(self):
        run_import(GEOJSON_FILE)
        self.assertFalse(Facility.objects.get(external_id="Q300").has_location)

    def test_numeric_ids_and_unusable_geometry(self):
        path = self.write_file(
            "numbers.geojson",
            json.dumps(
                {
                    "features": [
                        {
                            "properties": {"SYSTEM": 42, "NAME": "Field"},
                            "geometry": {"type": "Point", "coordinates": "nowhere"},
                        }
                    ]
                }
            ).encode(),
        )
        stdout, _ = run_import(path)
        self.assertIn("created: 1,", stdout)
        self.assertFalse(Facility.objects.get(external_id="42").has_location)


class UnreadableFileTests(ImportFacilitiesTestCase):
    def test_missing_file(self):
        with self.assertRaisesMessage(CommandError, "Could not read"):
            run_import(TESTDATA / "does_not_exist.csv")
        self.assertFalse(Facility.objects.exists())

    def test_unsupported_extension(self):
        with self.assertRaisesMessage(CommandError, "expected a .csv"):
            run_import(TESTDATA / "athletic_facilities.txt")

    def test_invalid_json(self):
        path = self.write_file("bad.geojson", b"{not json")
        with self.assertRaisesMessage(CommandError, "Could not read"):
            run_import(path)

    def test_json_that_is_not_a_feature_collection(self):
        path = self.write_file("list.json", b"[]")
        with self.assertRaisesMessage(CommandError, "FeatureCollection"):
            run_import(path)

    def test_file_that_is_not_utf8(self):
        path = self.write_file("latin1.csv", b"SYSTEM,NAME\nM1,Caf\xe9\n")
        with self.assertRaisesMessage(CommandError, "Could not read"):
            run_import(path)
