"""Fill the current semester's default seasons with a class league.

Run it once by hand. It is not in .ebextensions. It sends no email.

    python manage.py seed_class_league --roster PATH [--dry-run] [--today YYYY-MM-DD]

The roster file holds real names and emails, so keep it out of git
(.gitignore lists class-league-roster*.json). Its format:

    {
      "sports": ["Basketball", "Volleyball", "Futsal"],
      "division": "University-wide",
      "leader": "staff",
      "teams": [
        {"key": "staff",
         "names": {"Basketball": "The Istari",
                   "Volleyball": "The White Council",
                   "Futsal": "Grey Pilgrims FC"},
         "members": [{"first_name": "A", "last_name": "B",
                      "email": "x@nyu.edu"}]}
      ]
    }

- "sports": sport names. Each sport uses its current semester default season.
- "division": the division name for every team, in every season.
- "leader": the key of the team that wins all its played matches.
- "teams": two or more teams. Each team has a unique "key", a name for every
  sport and one or more members. The first member is the captain. Emails end
  in @nyu.edu and appear once per team.

For each sport the command:
- Skips the sport when its season is missing, draft or closed.
- Creates each team, unless the season has a team with that name. It uses an
  existing team unchanged.
- Gets each member with placeholder_for: an existing user, or a new
  placeholder. A member already on another team in the season is skipped.
- Creates a double round robin. About 60% of the rounds are played before
  today, with scores, but never before the season start date: early in the
  semester fewer rounds are played. The other rounds are upcoming, up to the
  season end.
  A (home, away) pair that has a match in the season gets no new match.

Each sport runs in one transaction. --dry-run rolls back every transaction.
The rows create no notifications and no audit log rows. A second run creates
nothing new.
"""

import datetime
import json
import random

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.placeholders import normalize_email, placeholder_for
from audit import signals as audit_signals
from facilities.models import Facility
from matches.models import Match
from matches.round_robin import pairings
from matches.standings import compute_standings
from notifications import signals as notification_signals
from teams.models import Roster, Season, Team
from teams.season_rules import SeasonState
from teams.semesters import current_semester, parse_date

PLAYED_SHARE = 0.6
DAYS_BETWEEN_ROUNDS = 4
START_TIMES = [datetime.time(18, 0), datetime.time(19, 30), datetime.time(21, 0)]
MATCH_LENGTH = datetime.timedelta(hours=1, minutes=15)


class _DryRun(Exception):
    """Raised inside a sport's transaction to roll it back."""


def load_roster(path):
    """Read and check the roster file. Return the data, or raise CommandError."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as error:
        raise CommandError(f"Can't read the roster file: {error.strerror}.")
    except json.JSONDecodeError as error:
        raise CommandError(f"The roster file is not valid JSON: {error.msg}.")
    validate_roster(data)
    return data


def _text(value):
    return isinstance(value, str) and value.strip() != ""


def validate_roster(data):
    """Raise CommandError for the first problem in the roster data."""
    if not isinstance(data, dict):
        raise CommandError("The roster file must hold a JSON object.")
    sports = data.get("sports")
    if not isinstance(sports, list) or not sports or not all(map(_text, sports)):
        raise CommandError('"sports" must be a list of sport names.')
    if len({sport.strip().lower() for sport in sports}) != len(sports):
        raise CommandError('"sports" lists a sport twice.')
    if not _text(data.get("division")):
        raise CommandError('"division" must be a division name.')
    teams = data.get("teams")
    if not isinstance(teams, list) or len(teams) < 2:
        raise CommandError('"teams" must be a list of two or more teams.')

    keys = set()
    names = {sport: set() for sport in sports}
    for number, team in enumerate(teams, start=1):
        if not isinstance(team, dict) or not _text(team.get("key")):
            raise CommandError(f'Team {number} needs a "key".')
        key = team["key"]
        if key in keys:
            raise CommandError(f'Team key "{key}" is used twice.')
        keys.add(key)
        team_names = team.get("names")
        if not isinstance(team_names, dict):
            raise CommandError(f'Team "{key}" needs "names", one for each sport.')
        for sport in sports:
            name = team_names.get(sport)
            if not _text(name):
                raise CommandError(f'Team "{key}" has no name for {sport}.')
            if name.strip().lower() in names[sport]:
                raise CommandError(f'Team "{key}": another team has its {sport} name.')
            names[sport].add(name.strip().lower())
        validate_members(key, team.get("members"))

    if data.get("leader") not in keys:
        raise CommandError('"leader" must be the key of one of the teams.')


def validate_members(key, members):
    if not isinstance(members, list) or not members:
        raise CommandError(f'Team "{key}" needs one or more members.')
    seen = {}
    for position, member in enumerate(members, start=1):
        where = f'Team "{key}", member {position}'
        if not isinstance(member, dict):
            raise CommandError(f"{where} must be an object.")
        for field in ("first_name", "last_name"):
            if not isinstance(member.get(field, ""), str):
                raise CommandError(f'{where}: "{field}" must be text.')
        raw = member.get("email")
        email = normalize_email(raw) if isinstance(raw, str) else ""
        local, _, domain = email.partition("@")
        if not local or domain != "nyu.edu" or " " in email:
            raise CommandError(f"{where}: {raw!r} is not an @nyu.edu email.")
        if email in seen:
            raise CommandError(f"{where} has the same email as member {seen[email]}.")
        seen[email] = position


def double_round_robin(teams):
    """Rounds of (home, away) pairs: every pair twice, home and away swapped."""
    first = pairings(teams)
    return first + [[(away, home) for home, away in pairs] for pairs in first]


def round_dates(today, round_count, played, sport_number, season):
    """Return (the date of each round, the number of played rounds).

    Played rounds end 1 to 3 days before today. Upcoming rounds start 1 to 3
    days after today. Rounds are DAYS_BETWEEN_ROUNDS apart, or closer when the
    season dates leave less room. An upcoming round past the season end gets
    None.

    Played rounds never fall before the season start_date. When they don't
    fit one a day, the last played round moves to the day before today. When
    they still don't fit, fewer rounds are played: the first starts on the
    start_date, and the rest become upcoming.
    """
    offset = 1 + sport_number % 3
    last_played = today - datetime.timedelta(days=offset)
    first_upcoming = today + datetime.timedelta(days=offset)
    start = season.start_date
    if start and played:
        if (last_played - start).days + 1 < played:
            last_played = today - datetime.timedelta(days=1)
        played = min(played, max(0, (last_played - start).days + 1))
    upcoming = round_count - played

    gap_back = DAYS_BETWEEN_ROUNDS
    if played > 1 and start:
        room = (last_played - start).days
        gap_back = min(gap_back, room // (played - 1))
    end = season.end_date or current_semester(today).end_date
    gap_ahead = DAYS_BETWEEN_ROUNDS
    if upcoming > 1:
        room = (end - first_upcoming).days
        gap_ahead = max(1, min(gap_ahead, room // (upcoming - 1)))

    dates = []
    for number in range(round_count):
        if number < played:
            day = last_played - datetime.timedelta(
                days=gap_back * (played - 1 - number)
            )
        else:
            day = first_upcoming + datetime.timedelta(
                days=gap_ahead * (number - played)
            )
            if day > end:
                day = None
        dates.append(day)
    return dates, played


def slot_window(day, slot):
    """Matches 1-3 of a round at START_TIMES; more go to the next days."""
    day = day + datetime.timedelta(days=slot // len(START_TIMES))
    starts_at = timezone.make_aware(
        datetime.datetime.combine(day, START_TIMES[slot % len(START_TIMES)])
    )
    return starts_at, starts_at + MATCH_LENGTH


def played_count(round_count):
    return min(round_count - 1, max(1, round(round_count * PLAYED_SHARE)))


def make_score(rng, sport, leader_side=None):
    """(home, away) scores. leader_side "home" or "away" makes that side win."""
    kind = sport.strip().lower()
    if kind == "volleyball":
        win, lose = 3, rng.choice([0, 1, 2])
        home_wins = rng.random() < 0.5
    elif kind == "basketball":
        a, b = rng.randint(45, 80), rng.randint(45, 80)
        if a == b:
            b = a - 1 if a > 45 else a + 1
        win, lose = max(a, b), min(a, b)
        home_wins = rng.random() < 0.5
    else:
        # Futsal and any other sport: goals, with draws allowed.
        a, b = rng.randint(0, 7), rng.randint(0, 7)
        if leader_side and a == b:
            a, b = (a + 1, b) if a < 7 else (a, b - 1)
        if a == b:
            return a, b
        win, lose = max(a, b), min(a, b)
        home_wins = rng.random() < 0.5
    if leader_side is not None:
        home_wins = leader_side == "home"
    return (win, lose) if home_wins else (lose, win)


def ensure_leader_first(season, leader, matches):
    """Change scores of `matches` until `leader` tops the standings.

    Each step, the team at the top loses one more match against a team that
    stays below the leader. Matches with the leader never change, and each
    match changes at most once. Return the number of changed matches.
    """
    changed = set()
    ordered = sorted(matches, key=lambda m: (m.starts_at, m.pk))
    while True:
        rows = compute_standings(season)
        if not rows or rows[0]["team"].pk == leader.pk:
            return len(changed)
        rival = rows[0]["team"]
        for match in ordered:
            if (
                match.pk in changed
                or not match.has_result
                or leader.pk in (match.home_team_id, match.away_team_id)
                or rival.pk not in (match.home_team_id, match.away_team_id)
                or _lost(match, rival)
            ):
                continue
            scores = (match.home_score, match.away_score)
            _make_lose(match, rival)
            match.full_clean()
            match.save()
            opponent = (
                match.away_team_id
                if match.home_team_id == rival.pk
                else match.home_team_id
            )
            if _ranks_above(season, opponent, leader):
                match.home_score, match.away_score = scores
                match.save()
                continue
            changed.add(match.pk)
            break
        else:
            return len(changed)


def _make_lose(match, team):
    """Change the score so `team` loses: swap a win, add a goal to a draw."""
    if match.home_score == match.away_score:
        if match.home_team_id == team.pk:
            match.away_score += 1
        else:
            match.home_score += 1
    else:
        match.home_score, match.away_score = match.away_score, match.home_score


def _ranks_above(season, team_id, leader):
    for row in compute_standings(season):
        if row["team"].pk == leader.pk:
            return False
        if row["team"].pk == team_id:
            return True
    return False


def _lost(match, team):
    if match.home_team_id == team.pk:
        return match.home_score < match.away_score
    return match.away_score < match.home_score


class Command(BaseCommand):
    help = "Create a class league from a roster file in this semester's seasons."

    def add_arguments(self, parser):
        parser.add_argument(
            "--roster", required=True, help="Path to the roster JSON file."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created and save nothing.",
        )
        parser.add_argument(
            "--today",
            type=parse_date,
            help="Use this date (YYYY-MM-DD) as today. For tests and local checks.",
        )

    def handle(self, *args, **options):
        data = load_roster(options["roster"])
        today = options["today"] or datetime.date.today()
        dry_run = options["dry_run"]
        self.verb = "would create" if dry_run else "created"
        term = current_semester(today).term

        # Seed rows are not league activity: no notifications, no audit rows.
        with notification_signals.muted(), audit_signals.muted():
            for number, sport in enumerate(data["sports"]):
                season = (
                    Season.objects.filter(term=term, sport__name__iexact=sport)
                    .select_related("sport")
                    .first()
                )
                if season is None:
                    self.stdout.write(f"{sport}: no {term} default season; skipped.")
                    continue
                if season.state in (SeasonState.DRAFT, SeasonState.CLOSED):
                    self.stdout.write(
                        f"{sport}: {season.name} is {season.get_state_display()}; "
                        "skipped."
                    )
                    continue
                try:
                    with transaction.atomic():
                        self.seed_sport(data, sport, season, today, number)
                        if dry_run:
                            raise _DryRun
                except _DryRun:
                    pass
        if dry_run:
            self.stdout.write("Dry run: nothing saved.")

    def seed_sport(self, data, sport, season, today, number):
        teams, leader, counts = self.ensure_teams(data, sport, season)
        created = self.ensure_matches(sport, season, teams, leader, today, number)
        # With no played matches (early in the season), nobody leads yet.
        has_results = Match.objects.filter(
            season=season, home_score__isnull=False
        ).exists()
        if leader is not None and has_results:
            if ensure_leader_first(season, leader, created):
                self.stdout.write(f"{sport}: changed scores so the leader is first.")
            rows = compute_standings(season)
            if rows and rows[0]["team"].pk != leader.pk:
                self.stderr.write(
                    f"{sport}: {leader.name} is not first in the standings."
                )
        played = sum(1 for match in created if match.has_result)
        self.stdout.write(
            f"{sport} ({season.name}): {self.verb} {counts['teams']} teams, "
            f"{counts['rosters']} roster entries, {counts['placeholders']} "
            f"placeholder accounts and {len(created)} matches "
            f"({played} played, {len(created) - played} upcoming)."
        )

    def ensure_teams(self, data, sport, season):
        """Return (teams in roster order, leader team, counts)."""
        division = season.divisions.filter(name__iexact=data["division"]).first()
        if division is None:
            self.stdout.write(
                f"{sport}: {season.name} has no division "
                f"\"{data['division']}\"; teams get no division."
            )
        counts = {"teams": 0, "rosters": 0, "placeholders": 0}
        teams = []
        leader = None
        for entry in data["teams"]:
            name = entry["names"][sport].strip()
            team = Team.objects.filter(season=season, name__iexact=name).first()
            if team is None:
                team = self.create_team(sport, season, division, entry, name, counts)
            if team is None:
                continue
            teams.append(team)
            if entry["key"] == data["leader"]:
                leader = team
        return teams, leader, counts

    def create_team(self, sport, season, division, entry, name, counts):
        busy = set(
            Roster.objects.filter(team__season=season).values_list(
                "player_id", flat=True
            )
        )
        players = []
        for position, member in enumerate(entry["members"], start=1):
            user, created = placeholder_for(
                member["email"],
                first_name=member.get("first_name", "").strip(),
                last_name=member.get("last_name", "").strip(),
            )
            counts["placeholders"] += created
            if user.pk in busy:
                self.stdout.write(
                    f"{sport}: {name}, member {position} is already on another "
                    "team in this season; skipped."
                )
                continue
            players.append((position, user))
        if not players:
            self.stdout.write(f"{sport}: {name} has no free members; skipped.")
            return None
        if players[0][0] != 1:
            self.stdout.write(
                f"{sport}: {name}, member {players[0][0]} is captain instead."
            )

        captain = players[0][1]
        team = Team(
            name=name,
            sport=season.sport,
            season=season,
            division=division,
            captain=captain,
        )
        team.save()
        counts["teams"] += 1
        for position, user in players:
            role = Roster.Role.CAPTAIN if user == captain else Roster.Role.PLAYER
            try:
                Roster(team=team, player=user, role=role).save()
            except ValidationError as error:
                self.stdout.write(
                    f"{sport}: {name}, member {position} skipped: "
                    f"{' '.join(error.messages)}"
                )
                continue
            counts["rosters"] += 1
        return team

    def ensure_matches(self, sport, season, teams, leader, today, number):
        """Create the missing double round-robin matches. Return them."""
        facilities = list(
            Facility.objects.filter(is_active=True, sports=season.sport)
        ) or list(Facility.objects.filter(is_active=True))
        if not facilities:
            self.stdout.write(f"{sport}: no active facility, so no matches.")
            return []

        rounds = double_round_robin(teams)
        if not rounds:
            return []
        dates, played = round_dates(
            today, len(rounds), played_count(len(rounds)), number, season
        )
        existing = set(
            Match.objects.filter(season=season).values_list(
                "home_team_id", "away_team_id"
            )
        )
        rng = random.Random(sport.strip().lower())
        created = []
        skipped_late = 0
        for round_number, (pairs, day) in enumerate(zip(rounds, dates)):
            for slot, (home, away) in enumerate(pairs):
                # Draw scores for every pair, so results don't depend on
                # which matches already exist.
                leader_side = None
                if leader is not None and leader in (home, away):
                    leader_side = "home" if home == leader else "away"
                score = make_score(rng, sport, leader_side)
                if (home.pk, away.pk) in existing:
                    continue
                if day is None:
                    skipped_late += 1
                    continue
                starts_at, ends_at = slot_window(day, slot)
                match = Match(
                    season=season,
                    home_team=home,
                    away_team=away,
                    facility=self.free_facility(facilities, slot, starts_at, ends_at),
                    starts_at=starts_at,
                    ends_at=ends_at,
                )
                if round_number < played:
                    match.home_score, match.away_score = score
                match.validate_schedulable()
                match.full_clean()
                match.save()
                created.append(match)
        if skipped_late:
            self.stdout.write(
                f"{sport}: {skipped_late} upcoming matches don't fit before the "
                "season end; not created."
            )
        return created

    def free_facility(self, facilities, index, starts_at, ends_at):
        """A facility with no other match in this window, if there is one."""
        start = index % len(facilities)
        rotated = facilities[start:] + facilities[:start]
        for facility in rotated:
            if not Match.objects.overlapping(facility, starts_at, ends_at).exists():
                return facility
        return rotated[0]
