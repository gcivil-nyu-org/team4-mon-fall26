"""Load NYU venues and NYC Parks facilities near campus from facilities/data/.

The files come from the Facilities Phase 1 analysis (build_playnyu_seed.py):
- city_facilities_near_nyu.csv: active NYC Parks athletic facilities within 3 km of
  Washington Square Park that permit a PlayNYU sport. Keyed by the dataset's `system`
  id, the same key import_facilities (#129) uses, so a later full import updates
  these rows instead of duplicating them.
- nyu_venues.csv: NYU facilities and Hudson River Park fields, which the city
  dataset doesn't include.

Re-running updates rows in place. Sports are linked by name and never created:
run seed_league_data first. Locally: python manage.py seed_facilities
"""

import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from facilities.models import Facility
from teams.catalog_rules import name_key
from teams.models import Sport

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BOROUGHS = {
    "M": Facility.Borough.MANHATTAN,
    "B": Facility.Borough.BROOKLYN,
    "Q": Facility.Borough.QUEENS,
    "X": Facility.Borough.BRONX,
    "R": Facility.Borough.STATEN_ISLAND,
}


def _sports(value, sports_by_key):
    names = [part.strip() for part in value.split(";") if part.strip()]
    return [sports_by_key[name_key(n)] for n in names if name_key(n) in sports_by_key]


def _coordinate(value):
    return Decimal(value).quantize(Decimal("0.000001")) if value else None


class Command(BaseCommand):
    help = "Load NYU venues and NYC Parks facilities near NYU from facilities/data/."

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default=str(DATA_DIR))

    @transaction.atomic
    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"])
        sports_by_key = {name_key(s.name): s for s in Sport.objects.all()}
        if not sports_by_key:
            self.stdout.write("No sports yet; facilities load without sports.")

        city = self._load(
            data_dir / "city_facilities_near_nyu.csv",
            sports_by_key,
            lambda row: dict(
                source=Facility.Source.CITY, external_id=row["external_id"]
            ),
            lambda row: dict(
                name=row["name"], borough=BOROUGHS.get(row["borough"], "")
            ),
        )
        nyu = self._load(
            data_dir / "nyu_venues.csv",
            sports_by_key,
            lambda row: dict(
                source=Facility.Source.NYU, external_id="", name=row["name"]
            ),
            lambda row: dict(
                borough=(
                    Facility.Borough.BROOKLYN
                    if "Brooklyn" in row["address"]
                    else Facility.Borough.MANHATTAN
                )
            ),
        )
        self.stdout.write(f"Facilities: {city} city, {nyu} NYU and partner venues.")

    def _load(self, path, sports_by_key, key, extra):
        count = 0
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                facility = Facility.objects.filter(**key(row)).first() or Facility(
                    **key(row)
                )
                for field, value in {**key(row), **extra(row)}.items():
                    setattr(facility, field, value)
                facility.address = row["address"]
                facility.latitude = _coordinate(row["latitude"])
                facility.longitude = _coordinate(row["longitude"])
                facility.is_active = True
                facility.save()
                facility.sports.set(_sports(row["sports"], sports_by_key))
                count += 1
        return count
