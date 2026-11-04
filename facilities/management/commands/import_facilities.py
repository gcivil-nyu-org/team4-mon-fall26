"""Import city facilities from a local NYC Parks Athletic Facilities export.

Usage: python manage.py import_facilities <path>

The file is a GeoJSON (.geojson, .json) or CSV (.csv) export. The command never
touches the network, and only ever reads or writes source=city rows.

No dataset has been formally selected yet (#4-#12), and #7 hasn't settled the
sport codes. Everything that depends on those decisions is in the three
constants below, so that is all that should need changing when they land. The
column names and values are assumptions: none have been checked against a real
export.
"""

import csv
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from facilities.models import Facility
from teams.catalog_rules import name_key
from teams.models import Sport

# What each value is read from: a CSV column or a GeoJSON feature property.
# Names are lowercase; the file's own column names are matched ignoring case.
COLUMN_MAP = {
    # Required. Must be unique per row and stable between exports, because it is
    # the upsert key. A park-level ID won't do if a park has several rows: every
    # repeat of an ID in a file is skipped.
    "external_id": "system",
    # Required.
    "name": "name",
    "address": "location",
    "borough": "borough",
    # Sport values, one or several separated by "," ";" or "/".
    "sports": "primary_sport",
    # Used if the file has them. They must be WGS84 degrees, as must geometry.
    "latitude": "lat",
    "longitude": "lon",
    # WKT in a CSV, such as "POINT (-73.99 40.73)". Used when latitude and
    # longitude are empty. A GeoJSON feature's own geometry is used the same way.
    "geometry": "the_geom",
}

# Lowercase dataset value -> Facility.Borough. Any other value leaves the
# borough blank, since it is optional and shouldn't cost us the row.
BOROUGH_MAP = {
    "m": Facility.Borough.MANHATTAN,
    "manhattan": Facility.Borough.MANHATTAN,
    "b": Facility.Borough.BROOKLYN,
    "brooklyn": Facility.Borough.BROOKLYN,
    "q": Facility.Borough.QUEENS,
    "queens": Facility.Borough.QUEENS,
    "x": Facility.Borough.BRONX,
    "bronx": Facility.Borough.BRONX,
    "the bronx": Facility.Borough.BRONX,
    "r": Facility.Borough.STATEN_ISLAND,
    "staten island": Facility.Borough.STATEN_ISLAND,
}

# Lowercase dataset value -> teams.Sport name, which is matched ignoring case
# and spacing. Sport rows are never created: a value that isn't here, or whose
# Sport doesn't exist, links nothing and is listed in the command output.
SPORT_MAP = {
    "basketball": "Basketball",
    "football": "American football",
    "soccer": "Soccer",
    "tennis": "Tennis",
    "volleyball": "Volleyball",
}

COORDINATE_PLACES = Decimal("0.000001")  # Facility.latitude.decimal_places
WKT_POSITION = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")
SPORT_SEPARATORS = re.compile(r"[,;/]")


def lowercase_keys(row):
    # DictReader puts surplus values in a short row under the key None.
    return {key.strip().lower(): value for key, value in row.items() if key}


def feature_to_row(feature):
    """Flatten a GeoJSON feature. A malformed one becomes an empty, skipped row."""
    if not isinstance(feature, dict):
        return {}
    properties = feature.get("properties")
    row = lowercase_keys(properties) if isinstance(properties, dict) else {}
    if feature.get("geometry"):
        row[COLUMN_MAP["geometry"]] = feature["geometry"]
    return row


def read_rows(path):
    """Return the file's rows as dicts, or raise CommandError."""
    suffix = Path(path).suffix.lower()
    if suffix not in (".csv", ".geojson", ".json"):
        raise CommandError(f"{path}: expected a .csv, .geojson or .json file.")
    try:
        # utf-8-sig also reads files without a byte order mark.
        with open(path, encoding="utf-8-sig", newline="") as source:
            if suffix == ".csv":
                return [lowercase_keys(row) for row in csv.DictReader(source)]
            data = json.load(source)
    except (OSError, ValueError, csv.Error) as exc:
        raise CommandError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise CommandError(f"{path}: expected a GeoJSON FeatureCollection.")
    return [feature_to_row(feature) for feature in data["features"]]


def text(row, field):
    value = row.get(COLUMN_MAP[field])
    return "" if value is None else str(value).strip()


def geojson_positions(coordinates):
    """Yield every (x, y) in GeoJSON coordinates of any nesting depth."""
    if not isinstance(coordinates, list):
        return
    if len(coordinates) >= 2 and all(
        isinstance(number, (int, float)) for number in coordinates[:2]
    ):
        yield coordinates[0], coordinates[1]
        return
    for item in coordinates:
        yield from geojson_positions(item)


def geometry_positions(geometry):
    if isinstance(geometry, str):
        return [(float(x), float(y)) for x, y in WKT_POSITION.findall(geometry)]
    if isinstance(geometry, dict):
        return list(geojson_positions(geometry.get("coordinates")))
    return []


def geometry_center(geometry):
    """Return (lat, lon) strings for a geometry, or empty strings if it has none.

    This is the middle of the bounding box: the exact spot for a point, and a
    close enough one for a facility's polygon.
    """
    positions = geometry_positions(geometry)
    if not positions:
        return "", ""
    xs, ys = zip(*positions)
    return str((min(ys) + max(ys)) / 2), str((min(xs) + max(xs)) / 2)


def coordinate(value):
    """Return value as a Decimal the model can hold, or None if it's empty."""
    if not value:
        return None
    try:
        return Decimal(value).quantize(COORDINATE_PLACES)
    except InvalidOperation as exc:
        raise ValidationError(f"Invalid coordinate: {value}") from exc


def location(row):
    lat, lon = text(row, "latitude"), text(row, "longitude")
    if not lat and not lon:
        lat, lon = geometry_center(row.get(COLUMN_MAP["geometry"]))
    return coordinate(lat), coordinate(lon)


class Command(BaseCommand):
    help = "Create or update city facilities from a local GeoJSON or CSV export."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the .geojson, .json or .csv file.")

    def handle(self, *args, **options):
        rows = read_rows(options["path"])
        self.sports = {name_key(sport.name): sport for sport in Sport.objects.all()}
        self.seen_ids = set()
        self.unmapped_sports = set()

        counts = Counter()
        for number, row in enumerate(rows, start=1):
            try:
                with transaction.atomic():
                    counts[self.import_row(row)] += 1
            except ValidationError as exc:
                counts["skipped"] += 1
                self.stderr.write(f"Row {number} skipped: {'; '.join(exc.messages)}")

        if self.unmapped_sports:
            unmapped = ", ".join(sorted(self.unmapped_sports))
            self.stdout.write(f"Sport values not linked: {unmapped}")
        self.stdout.write(
            self.style.SUCCESS(
                f"created: {counts['created']}, updated: {counts['updated']}, "
                f"skipped: {counts['skipped']}, unchanged: {counts['unchanged']}"
            )
        )

    def import_row(self, row):
        """Upsert one row and return "created", "updated" or "unchanged"."""
        external_id = text(row, "external_id")
        name = text(row, "name")
        if not external_id:
            raise ValidationError(f"no {COLUMN_MAP['external_id']} value")
        if not name:
            raise ValidationError(f"no {COLUMN_MAP['name']} value")
        # A second row can't win over the first, or each re-run would flip the
        # facility between them.
        if external_id in self.seen_ids:
            raise ValidationError(f"{external_id} is repeated in this file")

        facility = Facility.objects.filter(
            source=Facility.Source.CITY, external_id=external_id
        ).first()
        created = facility is None
        if created:
            facility = Facility(source=Facility.Source.CITY, external_id=external_id)
            old_sports = set()
        else:
            old_sports = set(facility.sports.all())

        fields = {"name": name, "address": text(row, "address")}
        fields["borough"] = BOROUGH_MAP.get(text(row, "borough").lower(), "")
        fields["latitude"], fields["longitude"] = location(row)
        old_values = {field: getattr(facility, field) for field in fields}
        for field, value in fields.items():
            setattr(facility, field, value)
        # save() only runs clean(). full_clean() also catches what would
        # otherwise reach the database, like a latitude out of range.
        facility.full_clean()

        new_sports = self.linked_sports(row)
        changed = (
            created
            or new_sports != old_sports
            or any(getattr(facility, field) != old for field, old in old_values.items())
        )
        if changed:
            facility.save()
            facility.sports.set(new_sports)
        self.seen_ids.add(external_id)
        if created:
            return "created"
        return "updated" if changed else "unchanged"

    def linked_sports(self, row):
        sports = set()
        for value in SPORT_SEPARATORS.split(text(row, "sports")):
            value = value.strip()
            sport_name = SPORT_MAP.get(value.lower())
            sport = self.sports.get(name_key(sport_name)) if sport_name else None
            if sport:
                sports.add(sport)
            elif value:
                self.unmapped_sports.add(value)
        return sports
