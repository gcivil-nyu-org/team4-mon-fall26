"""Move seasons to the next state by date.

- Open becomes active on the day after `registration_closes_on`.
- Active becomes closed on the day after `end_date`.

Draft and closed seasons never change. A season with `auto_state` off, or with
the date missing, never changes. The rule is `automatic_states` in
teams/season_rules.py. Each change goes through `Season.move_to`, and the audit
app logs it with no actor.

.ebextensions/django.config runs this on every deploy. README.md says how to run
it daily.

Locally: python manage.py advance_season_states [--today YYYY-MM-DD] [--dry-run]
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from teams.models import Season
from teams.season_rules import SeasonState


def parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise CommandError(f"--today must be YYYY-MM-DD, not {value!r}.")


class Command(BaseCommand):
    help = "Make open seasons active and active seasons closed, by date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--today",
            type=parse_date,
            help="Use this date (YYYY-MM-DD) as today. For tests and local checks.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the changes without saving them.",
        )

    def handle(self, *args, **options):
        today = options["today"] or timezone.localdate()
        dry_run = options["dry_run"]

        candidates = Season.objects.filter(
            auto_state=True, state__in=[SeasonState.OPEN, SeasonState.ACTIVE]
        ).order_by("start_date", "name", "pk")
        total = Season.objects.count()
        changed = 0
        for pk in candidates.values_list("pk", flat=True):
            with transaction.atomic():
                # Lock the row: a League Admin can change the season at the same time.
                season = Season.objects.select_for_update().get(pk=pk)
                steps = season.automatic_states(today)
                if not steps:
                    continue
                states = [season.state, *steps]
                if not dry_run:
                    for target in steps:
                        season.move_to(target)
            changed += 1
            path = " → ".join(SeasonState(state).label for state in states)
            self.stdout.write(f"  {season.name}: {path}")

        verb = "would change" if dry_run else "changed"
        prefix = "Season states (dry run)" if dry_run else "Season states"
        self.stdout.write(f"{prefix}: {changed} {verb}, {total - changed} unchanged.")
