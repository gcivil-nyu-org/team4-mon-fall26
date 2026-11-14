"""Round-robin scheduling: who plays whom, and the plan for a season.

`pairings` is pure. `plan_round_robin` reads the season's teams and matches
and saves nothing. `create_planned_matches` saves a plan in one transaction.
"""

import datetime
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from facilities.models import Facility
from teams.models import Team

from .models import Match


def pairings(teams):
    """Every pair of teams once, as rounds of (home, away) pairs.

    Circle method: a team plays at most once per round. With an odd number of
    teams, one team rests each round. Home and away games differ by at most
    one for every team (they are equal when the number of teams is odd).
    """
    teams = list(teams)
    if len(teams) < 2:
        return []
    slots = list(range(len(teams)))
    if len(slots) % 2:
        slots.append(None)  # the team paired with None rests that round
    even = len(teams) % 2 == 0
    last = len(slots) - 1
    rounds = []
    for _ in range(last):
        pairs = []
        for i in range(len(slots) // 2):
            a, b = slots[i], slots[-1 - i]
            if a is None or b is None:
                continue
            low, high = min(a, b), max(a, b)
            if even and high == last:
                # The team that never moves alternates by opponent.
                low_is_home = low % 2 == 1
            else:
                low_is_home = (low + high) % 2 == 1
            home, away = (low, high) if low_is_home else (high, low)
            pairs.append((teams[home], teams[away]))
        rounds.append(pairs)
        slots.insert(1, slots.pop())
    return rounds


@dataclass
class PlannedMatch:
    """An unsaved match, with the scheduled matches its booking overlaps."""

    match: Match
    overlaps: list = field(default_factory=list)


@dataclass
class PlannedRound:
    number: int
    date: datetime.date
    matches: list


@dataclass
class Plan:
    season: object
    rounds: list  # only the rounds that have a match to create
    pair_count: int  # every pair the round-robin covers
    skipped: int  # pairs that already have a match in the season

    @property
    def matches(self):
        return [planned for round_ in self.rounds for planned in round_.matches]

    @property
    def overlap_count(self):
        return sum(1 for planned in self.matches if planned.overlaps)

    @property
    def token(self):
        """Identifies exactly what the preview showed.

        Confirming only counts for the same matches and the same overlaps, so
        a stale preview can't create a different schedule.
        """
        shown = [
            (
                planned.match.home_team_id,
                planned.match.away_team_id,
                planned.match.facility_id,
                planned.match.starts_at.timestamp(),
                planned.match.ends_at.timestamp(),
                [overlap.pk for overlap in planned.overlaps],
            )
            for planned in self.matches
        ]
        return salted_hmac(
            "matches.round_robin", repr((self.season.pk, self.skipped, shown))
        ).hexdigest()


def _team_groups(season, division):
    """The teams to pair, one list per sport: a match needs one sport."""
    teams = Team.objects.filter(season=season).select_related("sport")
    if division is not None:
        teams = teams.filter(division=division)
    groups = {}
    for team in teams.order_by("sport__name", "name", "pk"):
        groups.setdefault(team.sport_id, []).append(team)
    return list(groups.values())


def _existing_pairs(season):
    """Pairs with a match in the season, in either home and away order.

    Cancelled matches count. A cancellation is an admin's decision, so the
    generator doesn't book that pair again without being asked.
    """
    return {
        frozenset(pair)
        for pair in Match.objects.filter(season=season).values_list(
            "home_team_id", "away_team_id"
        )
    }


def _overlapping(booked, facility, starts_at, ends_at):
    """Same rule as MatchQuerySet.overlapping, on matches already loaded."""
    return [
        match
        for match in booked
        if match.facility_id == facility.pk
        and match.starts_at < ends_at
        and match.ends_at > starts_at
    ]


def _book(pairs, season, starts_at, match_length, facilities, sport_facilities, turn):
    """Give each pair of a round a facility and a time.

    The round starts at `starts_at`. A pair moves to the next time slot only
    when the plan itself fills every facility in the slot, so planned matches
    never overlap each other. An overlap with an existing match is a warning.
    """
    round_end = starts_at + match_length * len(pairs)
    booked = list(
        Match.objects.scheduled()
        .filter(facility__in=facilities, starts_at__lt=round_end, ends_at__gt=starts_at)
        .select_related("facility", "home_team__sport", "away_team__sport")
    )
    taken = set()  # (facility pk, slot) the plan uses in this round
    planned = []
    for home, away in pairs:
        choices = sport_facilities.get(home.sport_id) or facilities
        start = turn % len(choices)
        turn += 1
        rotated = choices[start:] + choices[:start]
        slot = 0
        while True:
            free = [f for f in rotated if (f.pk, slot) not in taken]
            if free:
                break
            slot += 1
        slot_start = starts_at + match_length * slot
        slot_end = slot_start + match_length
        clashes = {f.pk: _overlapping(booked, f, slot_start, slot_end) for f in free}
        facility = next((f for f in free if not clashes[f.pk]), free[0])
        taken.add((facility.pk, slot))
        planned.append(
            PlannedMatch(
                match=Match(
                    season=season,
                    home_team=home,
                    away_team=away,
                    facility=facility,
                    starts_at=slot_start,
                    ends_at=slot_end,
                ),
                overlaps=clashes[facility.pk],
            )
        )
    return planned


def plan_round_robin(
    season,
    *,
    first_date,
    start_time,
    match_length,
    days_between_rounds,
    division=None,
    facilities=None,
):
    """Plan the season's missing round-robin matches. Saves nothing.

    Teams only meet teams of their own sport. Round N of every sport is on the
    same day: `first_date` plus N times `days_between_rounds`. A round keeps
    its day when some of its pairs already have a match, so a second run fills
    the gaps on the same days. Times are in the current time zone (New York).

    With no `facilities`, every active facility is used, and a match prefers
    the facilities that list its sport.
    """
    sport_facilities = {}
    if facilities:
        facilities = list(facilities)
    else:
        facilities = list(
            Facility.objects.filter(is_active=True).prefetch_related("sports")
        )
        for facility in facilities:
            for sport in facility.sports.all():
                sport_facilities.setdefault(sport.pk, []).append(facility)
    if not facilities:
        raise ValueError("A round-robin plan needs at least one facility.")

    existing = _existing_pairs(season)
    by_round = {}
    pair_count = skipped = 0
    for teams in _team_groups(season, division):
        for number, pairs in enumerate(pairings(teams)):
            for home, away in pairs:
                pair_count += 1
                if frozenset((home.pk, away.pk)) in existing:
                    skipped += 1
                    continue
                by_round.setdefault(number, []).append((home, away))

    rounds = []
    turn = 0
    for number in sorted(by_round):
        date = first_date + datetime.timedelta(days=days_between_rounds * number)
        starts_at = timezone.make_aware(datetime.datetime.combine(date, start_time))
        matches = _book(
            by_round[number],
            season,
            starts_at,
            match_length,
            facilities,
            sport_facilities,
            turn,
        )
        turn += len(matches)
        rounds.append(PlannedRound(number=number + 1, date=date, matches=matches))
    return Plan(season=season, rounds=rounds, pair_count=pair_count, skipped=skipped)


def create_planned_matches(plan, created_by=None):
    """Save every planned match, or none of them.

    Each match passes the same checks as a single scheduled match. The first
    one that fails stops the run, and the error names it.
    """
    created = []
    with transaction.atomic():
        for planned in plan.matches:
            match = planned.match
            match.created_by = created_by
            try:
                match.validate_schedulable()
                if not match.facility.is_active:
                    raise ValidationError("This facility isn't available.")
                match.full_clean()
            except ValidationError as error:
                when = timezone.localtime(match.starts_at)
                raise ValidationError(
                    f"{match} on {when:%b} {when.day} can't be scheduled: "
                    f"{' '.join(error.messages)} No matches were created."
                ) from error
            match.save()
            created.append(match)
    return created
