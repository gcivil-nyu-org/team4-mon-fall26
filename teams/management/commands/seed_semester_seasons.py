"""Create the default semester seasons for every sport.

For each Sport, this makes sure the current semester's season exists (open) and the
next semester's season exists (draft). New seasons get the default divisions.
Existing seasons are never changed, so admins can edit them freely.

teams/default_seasons.py holds the logic. The Sports page and the Django admin also
call it when a League Admin adds a sport.

A new season gets a registration close date REGISTRATION_WEEKS after the semester
start. advance_season_states makes the season active on the day after that date.
A season created after that date gets no date, so it stays open until a League
Admin sets a date or starts the season.

.ebextensions/django.config runs this after seed_league_data on every deploy.

Locally: python manage.py seed_semester_seasons [--today YYYY-MM-DD]
"""

import datetime
from django.core.management.base import BaseCommand, CommandError

from teams.default_seasons import (  # noqa: F401 (other code imports these from here)
    DEFAULT_DIVISIONS,
    REGISTRATION_WEEKS,
    default_registration_close,
    ensure_default_seasons,
)
from teams.models import Sport
from teams.semesters import (  # noqa: F401 (tests import these from here)
    SEMESTERS,
    Semester,
    current_semester,
    next_semester,
    semesters_in_year,
)

# Seasons that ensure_default_seasons makes for each sport.
SEASONS_PER_SPORT = 2


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
        created = existing = 0
        for sport in Sport.objects.order_by("name"):
            made = len(ensure_default_seasons(sport, today))
            created += made
            existing += SEASONS_PER_SPORT - made
        self.stdout.write(
            f"Semester seasons: {created} created, {existing} already there."
        )
