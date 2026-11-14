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

from django.core.management.base import BaseCommand

from teams.default_seasons import (  # noqa: F401 (other code imports these from here)
    DEFAULT_DIVISIONS,
    REGISTRATION_WEEKS,
    default_registration_close,
    default_semesters,
    ensure_default_seasons,
)
from teams.models import Season, Sport
from teams.semesters import (  # noqa: F401 (tests import these from here)
    SEMESTERS,
    Semester,
    current_semester,
    next_semester,
    parse_date,
    semesters_in_year,
)


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
        terms = [semester.term for semester, _ in default_semesters(today)]
        created = existing = 0
        for sport in Sport.objects.order_by("name"):
            made = len(ensure_default_seasons(sport, today))
            created += made
            total = Season.objects.filter(sport=sport, term__in=terms).count()
            existing += total - made
        self.stdout.write(
            f"Semester seasons: {created} created, {existing} already there."
        )
