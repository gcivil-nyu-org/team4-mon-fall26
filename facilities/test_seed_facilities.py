import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from teams.models import Sport

from .management.commands.seed_facilities import DATA_DIR
from .models import Facility

CITY_HEADER = [
    "external_id",
    "name",
    "address",
    "borough",
    "sports",
    "latitude",
    "longitude",
]
NYU_HEADER = ["name", "address", "latitude", "longitude", "sports", "managed_by"]


def write(path, header, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


class SeedFacilitiesTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write(
            self.dir / "city_facilities_near_nyu.csv",
            CITY_HEADER,
            [
                [
                    "M098-BASKETBALL-1",
                    "Washington Square Park – Full Court 1",
                    "WASHINGTON SQUARE",
                    "M",
                    "Basketball",
                    "40.731",
                    "-73.997",
                ],
                [
                    "M144-SOCCER-1",
                    "Pier Field – Soccer",
                    "",
                    "",
                    "Soccer; Squash",
                    "40.72",
                    "-74.01",
                ],
            ],
        )
        write(
            self.dir / "nyu_venues.csv",
            NYU_HEADER,
            [
                [
                    "Paulson Center",
                    "181 Mercer Street, New York, NY 10012",
                    "40.72679",
                    "-73.99795",
                    "Basketball; Swimming",
                    "NYU",
                ],
                [
                    "Brooklyn Athletic Facility",
                    "6 MetroTech Center, Brooklyn, NY 11201",
                    "40.694234",
                    "-73.98665",
                    "Fitness",
                    "NYU",
                ],
            ],
        )
        Sport.objects.create(name="Basketball")
        Sport.objects.create(name="Soccer")

    def tearDown(self):
        self.tmp.cleanup()

    def run_seed(self, data_dir=None):
        out = StringIO()
        call_command(
            "seed_facilities", f"--data-dir={data_dir or self.dir}", stdout=out
        )
        return out.getvalue()

    def test_loads_city_and_nyu_facilities_with_sports(self):
        output = self.run_seed()
        self.assertIn("2 city, 2 NYU", output)
        court = Facility.objects.get(external_id="M098-BASKETBALL-1")
        self.assertEqual(court.source, Facility.Source.CITY)
        self.assertEqual(court.borough, Facility.Borough.MANHATTAN)
        self.assertEqual(str(court.latitude), "40.731000")
        self.assertEqual(
            list(court.sports.values_list("name", flat=True)), ["Basketball"]
        )
        paulson = Facility.objects.get(name="Paulson Center")
        self.assertEqual(
            (paulson.source, paulson.external_id), (Facility.Source.NYU, "")
        )
        self.assertEqual(
            list(paulson.sports.values_list("name", flat=True)), ["Basketball"]
        )

    def test_unknown_sports_and_boroughs_are_skipped(self):
        self.run_seed()
        pier = Facility.objects.get(external_id="M144-SOCCER-1")
        self.assertEqual(list(pier.sports.values_list("name", flat=True)), ["Soccer"])
        self.assertEqual(pier.borough, "")
        self.assertEqual(
            Facility.objects.get(name="Brooklyn Athletic Facility").borough,
            Facility.Borough.BROOKLYN,
        )

    def test_rerunning_updates_instead_of_duplicating(self):
        self.run_seed()
        Facility.objects.filter(external_id="M098-BASKETBALL-1").update(
            name="Old name", is_active=False
        )
        self.run_seed()
        self.assertEqual(Facility.objects.count(), 4)
        court = Facility.objects.get(external_id="M098-BASKETBALL-1")
        self.assertEqual(court.name, "Washington Square Park – Full Court 1")
        self.assertTrue(court.is_active)

    def test_works_before_sports_exist(self):
        Sport.objects.all().delete()
        output = self.run_seed()
        self.assertIn("No sports yet", output)
        self.assertEqual(Facility.objects.count(), 4)

    def test_committed_data_files_load(self):
        call_command("seed_league_data", stdout=StringIO())
        output = self.run_seed(DATA_DIR)
        self.assertIn("154 city, 8 NYU", output)
        self.assertEqual(
            Facility.objects.filter(source=Facility.Source.CITY).count(), 154
        )
        self.assertTrue(
            Facility.objects.filter(
                name="John A. Paulson Center", sports__name="Volleyball"
            ).exists()
        )
