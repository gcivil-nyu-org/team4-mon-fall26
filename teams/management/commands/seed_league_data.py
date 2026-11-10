"""Create the PlayNYU sports, and optionally an open demo season.

The deployed SQLite database resets on every deploy, so .ebextensions/django.config
runs this after migrate. Without sports nobody can create a team (Sport is required).
Sports come from the Facilities Phase 1 sport list (docs and #105).

Locally: python manage.py seed_league_data [--demo-season]
On a deploy, the demo season is created when SEED_DEMO_SEASON is set (`eb setenv`).
"""

import datetime
import os

from django.core.management.base import BaseCommand

from teams.catalog_rules import name_key
from teams.models import Season, Sport
from teams.season_rules import SeasonState

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

DEMO_SEASON = {
    "name": "Fall 2026",
    "start_date": datetime.date(2026, 9, 1),
    "end_date": datetime.date(2026, 12, 15),
}


class Command(BaseCommand):
    help = "Create the PlayNYU sports and, with --demo-season, an open demo season."

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo-season",
            action="store_true",
            help="Also create an open 'Fall 2026' season if it doesn't exist.",
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

        if options["demo_season"] or os.environ.get("SEED_DEMO_SEASON"):
            season, made = Season.objects.get_or_create(
                name=DEMO_SEASON["name"],
                defaults={**DEMO_SEASON, "state": SeasonState.OPEN},
            )
            self.stdout.write(
                f"Season {season.name}: {'created (open)' if made else 'already there'}."
            )
