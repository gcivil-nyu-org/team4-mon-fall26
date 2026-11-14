"""Fill the current semester's default seasons with demo teams and matches.

For the testing site only, so standings, schedules and the dashboard have data.
.ebextensions/django.config runs this on every deploy, after seed_demo_users,
seed_semester_seasons and seed_facilities. It does nothing unless
SEED_DEMO_LEAGUE is set (`eb setenv`), so production gets no demo data.

It only adds what is missing and never changes existing teams or matches:
- A demo team is a team with a name from DEMO_TEAMS whose captain is a demo
  player. An existing team keeps its roster and division as they are.
- A demo match is a match between two demo teams. A pairing that already has a
  match (even a cancelled one) gets no new one.

Demo rows create no notifications and no audit log rows: the writes run inside
notifications.signals.muted() and audit.signals.muted(). Validation still runs.

Locally: python manage.py seed_demo_league --force [--today YYYY-MM-DD]
"""

import datetime
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.management.commands.seed_demo_users import DEMO_USERS
from audit import signals as audit_signals
from facilities.models import Facility
from matches.models import Match
from notifications import signals as notification_signals
from teams.models import Roster, Season, Team
from teams.season_rules import SeasonAction
from teams.semesters import current_semester, parse_date

# (team name, division name, member emails). The first member is the captain.
# A player can be on one team per season, so no email appears twice.
# demo.player9 and demo.player10 stay off these teams, to demo free agents.
DEMO_TEAMS = [
    (
        "Demo Violets",
        "University-wide",
        ["demo.captain1@nyu.edu", "demo.player1@nyu.edu", "demo.player2@nyu.edu"],
    ),
    (
        "Demo Bobcats",
        "University-wide",
        ["demo.captain2@nyu.edu", "demo.player3@nyu.edu", "demo.player4@nyu.edu"],
    ),
    (
        "Demo Torches",
        "CAS",
        ["demo.captain3@nyu.edu", "demo.player5@nyu.edu", "demo.player6@nyu.edu"],
    ),
    (
        "Demo Arches",
        "CAS",
        ["demo.captain4@nyu.edu", "demo.player7@nyu.edu", "demo.player8@nyu.edu"],
    ),
]

# (home, away) scores for played matches, used in order. Fixed, so every run
# gives the same results.
SCORES = [(3, 1), (2, 2), (0, 1), (4, 2), (1, 0), (2, 3)]

DAYS_BETWEEN_MATCHES = 3
START_TIME = datetime.time(18, 0)
MATCH_LENGTH = datetime.timedelta(hours=1)


def round_robin(teams):
    """Every pair of teams once, as (home, away), round by round."""
    teams = list(teams)
    if len(teams) % 2:
        teams.append(None)  # the team paired with None rests that round
    pairs = []
    for round_number in range(len(teams) - 1):
        for i in range(len(teams) // 2):
            home, away = teams[i], teams[-1 - i]
            if home is None or away is None:
                continue
            # Swap every other round so no team is always at home.
            pairs.append((away, home) if round_number % 2 else (home, away))
        teams.insert(1, teams.pop())
    return pairs


def match_window(today, index, played):
    """Played matches end before today; the others start after today."""
    if index < played:
        days = DAYS_BETWEEN_MATCHES * (index - played)
    else:
        days = DAYS_BETWEEN_MATCHES * (index - played + 1)
    starts_at = timezone.make_aware(
        datetime.datetime.combine(today + datetime.timedelta(days=days), START_TIME)
    )
    return starts_at, starts_at + MATCH_LENGTH


class Command(BaseCommand):
    help = "Create demo teams and matches in the current semester's default seasons."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when SEED_DEMO_LEAGUE is not set.",
        )
        parser.add_argument(
            "--today",
            type=parse_date,
            help="Use this date (YYYY-MM-DD) as today. For tests and local checks.",
        )

    def handle(self, *args, **options):
        if not (options["force"] or os.environ.get("SEED_DEMO_LEAGUE")):
            self.stdout.write("SEED_DEMO_LEAGUE not set; no demo league seeded.")
            return

        emails = [email for email, _, _ in DEMO_USERS]
        self.demo_users = {
            user.username: user
            for user in get_user_model().objects.filter(username__in=emails)
        }
        if not self.demo_users:
            self.stdout.write("No demo players; run seed_demo_users first.")
            return

        today = options["today"] or datetime.date.today()
        seasons = Season.objects.filter(
            term=current_semester(today).term, sport__isnull=False
        ).order_by("name", "pk")
        teams_created = matches_created = 0
        # Demo data is not league activity: no notifications, no audit rows.
        with notification_signals.muted(), audit_signals.muted():
            for number, season in enumerate(seasons):
                with transaction.atomic():
                    teams, created = self.ensure_teams(season)
                    teams_created += created
                    matches_created += self.ensure_matches(season, teams, today, number)
        self.stdout.write(
            f"Demo league: {teams_created} teams and {matches_created} matches "
            f"created in {len(seasons)} seasons."
        )

    def ensure_teams(self, season):
        """Return the season's demo teams and how many of them are new."""
        demo_user_ids = {user.pk for user in self.demo_users.values()}
        divisions = {division.name: division for division in season.divisions.all()}
        busy = set(
            Roster.objects.filter(team__season=season).values_list(
                "player_id", flat=True
            )
        )
        teams = []
        created = 0
        for name, division_name, emails in DEMO_TEAMS:
            team = Team.objects.filter(season=season, name=name).first()
            if team is not None:
                # Someone else's team with this name is not a demo team.
                if team.captain_id in demo_user_ids:
                    teams.append(team)
                continue
            if not season.allows(SeasonAction.CREATE_TEAM):
                continue
            # A demo player who already joined a real team here stays there.
            members = [
                self.demo_users[email]
                for email in emails
                if email in self.demo_users and self.demo_users[email].pk not in busy
            ]
            if not members:
                continue
            captain = members[0]
            team = Team(
                name=name,
                sport=season.sport,
                season=season,
                division=divisions.get(division_name),
                captain=captain,
            )
            team.save()
            for player in members:
                role = Roster.Role.CAPTAIN if player == captain else Roster.Role.PLAYER
                Roster(team=team, player=player, role=role).save()
            teams.append(team)
            created += 1
        return teams, created

    def ensure_matches(self, season, teams, today, season_number):
        """Create the missing round-robin matches. Return how many."""
        if not season.allows(SeasonAction.SCHEDULE_MATCH):
            return 0
        facilities = list(
            Facility.objects.filter(is_active=True, sports=season.sport)
        ) or list(Facility.objects.filter(is_active=True))
        if not facilities:
            self.stdout.write(f"{season.name}: no facility, so no matches.")
            return 0

        pairs = round_robin(teams)
        played = len(pairs) // 2
        created = 0
        for index, (home, away) in enumerate(pairs):
            if Match.objects.filter(
                season=season, home_team=home, away_team=away
            ).exists():
                continue
            starts_at, ends_at = match_window(today, index, played)
            match = Match(
                season=season,
                home_team=home,
                away_team=away,
                facility=self.free_facility(facilities, index, starts_at, ends_at),
                starts_at=starts_at,
                ends_at=ends_at,
            )
            if index < played:
                # Shift by season so the seasons don't all have the same table.
                match.home_score, match.away_score = SCORES[
                    (index + season_number) % len(SCORES)
                ]
            match.validate_schedulable()
            match.full_clean()
            match.save()
            created += 1
        return created

    def free_facility(self, facilities, index, starts_at, ends_at):
        """A facility with no other match in this window, if there is one."""
        start = index % len(facilities)
        rotated = facilities[start:] + facilities[:start]
        for facility in rotated:
            if not Match.objects.overlapping(facility, starts_at, ends_at).exists():
                return facility
        return rotated[0]
