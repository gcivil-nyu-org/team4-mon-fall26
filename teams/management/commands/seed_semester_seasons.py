"""Create the default semester seasons for every sport.

For each Sport, this makes sure the current semester's season exists (open) and the
next semester's season exists (draft). New seasons get the default divisions.
Existing seasons are never changed, so admins can edit them freely.

.ebextensions/django.config runs this after seed_league_data on every deploy.

Locally: python manage.py seed_semester_seasons [--today YYYY-MM-DD]
"""

import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from teams.models import Division, Season, Sport
from teams.season_rules import SeasonState
from teams.semesters import (  # noqa: F401 (tests import these from here)
    SEMESTERS,
    Semester,
    current_semester,
    next_semester,
    semesters_in_year,
)

# Divisions added to each new semester season. Edit this list to change the defaults.
DEFAULT_DIVISIONS = [
    "University-wide",
    "CAS",
    "Tandon",
    "Stern",
    "Steinhardt",
    "Tisch",
    "Inter-school",
]


def parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise CommandError(f"--today must be YYYY-MM-DD, not {value!r}.")


class Command(BaseCommand):
    help = "Create this and next semester's season for every sport, if missing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--today",
            type=parse_date,
            help="Use this date (YYYY-MM-DD) as today. For tests and local checks.",
        )

    def handle(self, *args, **options):
        today = options["today"] or datetime.date.today()
        current = current_semester(today)
        upcoming = next_semester(current)

        created = existing = 0
        for sport in Sport.objects.order_by("name"):
            for semester, state in (
                (current, SeasonState.OPEN),
                (upcoming, SeasonState.DRAFT),
            ):
                if self.ensure_season(sport, semester, state):
                    created += 1
                else:
                    existing += 1
        self.stdout.write(
            f"Semester seasons: {created} created, {existing} already there."
        )

    def ensure_season(self, sport, semester, state):
        """Create the season and its divisions if missing. Return True if created."""
        with transaction.atomic():
            season, made = Season.objects.get_or_create(
                sport=sport,
                term=semester.term,
                defaults={
                    "name": f"{semester.label} {sport.name}",
                    "start_date": semester.start_date,
                    "end_date": semester.end_date,
                    "state": state,
                },
            )
            if made:
                for name in DEFAULT_DIVISIONS:
                    Division(season=season, name=name).save()
        return made
