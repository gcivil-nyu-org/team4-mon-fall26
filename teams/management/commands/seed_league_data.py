"""Create the PlayNYU sports.

.ebextensions/django.config runs this after migrate on every deploy, and it only
adds what is missing. Without sports nobody can create a team (Sport is required).
Sports come from the Facilities Phase 1 sport list (docs and #105).

Locally: python manage.py seed_league_data

This command creates no season. seed_semester_seasons creates one season per
sport per semester. --demo-season and SEED_DEMO_SEASON once created a plain
"Fall 2026" season with no sport; both are still accepted, so an old deploy
setting cannot break a deploy, but they do nothing (#212). An existing
"Fall 2026" season is never read, changed or deleted here.
"""

import os

from django.core.management.base import BaseCommand

from teams.catalog_rules import name_key
from teams.models import Sport

SPORTS = [
    "Basketball",
    "Cricket",
    "Flag football",
    "Futsal",
    "Pickleball",
    "Soccer",
    "Softball",
    "Ultimate frisbee",
    "Volleyball",
]

DEMO_SEASON_RETIRED = (
    "{source} is retired and does nothing: seed_semester_seasons creates the "
    "seasons. No season was created or changed."
)


class Command(BaseCommand):
    help = "Create the PlayNYU sports."

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo-season",
            action="store_true",
            help="Retired. Does nothing; seed_semester_seasons creates the seasons.",
        )

    def handle(self, *args, **options):
        existing = {name_key(sport.name) for sport in Sport.objects.only("name")}
        created = 0
        for name in SPORTS:
            if name_key(name) not in existing:
                Sport.objects.create(name=name)
                created += 1
        self.stdout.write(
            f"Sports: {created} created, {len(SPORTS) - created} already there."
        )

        if options["demo_season"]:
            self.stdout.write(DEMO_SEASON_RETIRED.format(source="--demo-season"))
        if os.environ.get("SEED_DEMO_SEASON"):
            self.stdout.write(DEMO_SEASON_RETIRED.format(source="SEED_DEMO_SEASON"))
