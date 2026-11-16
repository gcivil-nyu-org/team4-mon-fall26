"""Give known sports their default periods where they still have 4 Q (#262).

Run once by hand where sports were created after migration 0014 (a fresh
database seeded by seed_league_data before #262). Run --dry-run first. This is
not a deploy step.

A sport changes only when its name is in teams/sport_defaults.py with periods
other than 4 Q, it still has exactly 4 Q, and no match of the sport has period
scores (#228: a new count would relabel them).
"""

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from teams.catalog_rules import name_key
from teams.models import Sport
from teams.sport_defaults import DEFAULT_PERIODS, SPORT_PERIODS


class Command(BaseCommand):
    help = "Give known sports with 4 Q their default periods. Run by hand."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the changes and write nothing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        period_scores = apps.get_model("matches", "MatchPeriodScore").objects
        fixed = kept = skipped = 0
        with transaction.atomic():
            for sport in Sport.objects.order_by("name"):
                target = SPORT_PERIODS.get(name_key(sport.name))
                if target is None or target == DEFAULT_PERIODS:
                    continue
                stored = (sport.period_count, sport.period_label)
                if stored != DEFAULT_PERIODS:
                    kept += 1
                    self.stdout.write(
                        f"{sport.name}: kept ({stored[0]} {stored[1]}, "
                        "set by an admin)."
                    )
                    continue
                # Check before the save, so Sport.clean never raises.
                if period_scores.filter(match__home_team__sport=sport).exists():
                    skipped += 1
                    self.stdout.write(f"{sport.name}: skipped (period scores stored).")
                    continue
                fixed += 1
                count, label = target
                if dry_run:
                    self.stdout.write(f"{sport.name}: would fix to {count} {label}.")
                    continue
                sport.period_count, sport.period_label = count, label
                sport.save(update_fields=["period_count", "period_label"])
                self.stdout.write(f"{sport.name}: fixed to {count} {label}.")
        prefix = "Dry run: " if dry_run else ""
        self.stdout.write(f"{prefix}Fixed {fixed}, kept {kept}, skipped {skipped}.")
