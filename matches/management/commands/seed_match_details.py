"""Add period scores, appearances and player stats to scored matches.

Run it by hand, after seed_class_league. It is not in .ebextensions.

    python manage.py seed_match_details [--dry-run] [--season PK ...] [--seed N]

On Elastic Beanstalk (see docs/DATABASE.md, "Class league on Elastic
Beanstalk", for the first steps):

    eb ssh <environment>
    source /var/app/venv/*/bin/activate
    cd /var/app/current
    export $(sudo /opt/elasticbeanstalk/bin/get-config --output YAML environment \\
        | sed -r 's/: /=/' | xargs)
    python manage.py seed_match_details --dry-run
    python manage.py seed_match_details

The command fills a match only when all of these are true:
- Both scores are set and the match is not cancelled.
- The season is open, active or closed (not draft).
- The match has no period score, no player stat and no appearance.
- Each team has one or more players on its roster.

For each such match:
- Appearances: every roster player, or all but one at random (rosters of 3
  or more).
- Period scores: the final score split over the sport's period_count periods.
  The periods add up exactly to home_score and away_score.
- Player stats, for the sport's event types:
  - The scoring type (Goal, Goals, Point, Points or Pts) adds up exactly to
    each team's score, over the players who appeared.
  - Assists: a team has no more assists than scoring plays, so never more
    assists than goals.
  - Other types get small random values. Zeros are not stored.

Volleyball-style sports (period label "Set", or the name Volleyball) store
sets won as the final score (seed_class_league writes 3-0, 3-1 or 3-2).
save_match_sheet makes the final score the sum of the periods, so set points
(25-20, ...) would change the final score. These sports get no periods and no
scoring stat; they get appearances and the other stats only.

It writes through matches.stats.save_match_sheet, with its validation, one
transaction per match. A draw comes from random.Random(f"{seed}:{match.pk}"),
so a run gives the same rows each time. A second run changes nothing, because
filled matches are skipped. --dry-run rolls back every transaction.

It never changes a final score, standings, a cancelled match or a match with
details. The rows create no notifications and no audit log rows.
"""

import random
from collections import Counter, defaultdict

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef

from audit import signals as audit_signals
from matches.models import Match, MatchAppearance, MatchPeriodScore, PlayerStat
from matches.stats import save_match_sheet
from notifications import signals as notification_signals
from teams.models import EventType, Roster, Season
from teams.season_rules import SeasonState

SCORING_NAMES = {"goal", "goals", "point", "points", "pts"}
ASSIST_NAMES = {"assist", "assists", "ast"}
# Cards and fouls are rare: a 1 for about one player in ten.
RARE_WORDS = ("card", "foul", "ejection", "penalt", "own goal")
ASSIST_SHARE = 0.6

SKIP_CANCELLED = "cancelled"
SKIP_UNSCORED = "no final score"
SKIP_DRAFT = "draft season"
SKIP_DETAILS = "already have details"
SKIP_NO_PLAYERS = "a team has no roster players"


class _DryRun(Exception):
    """Raised inside a match's transaction to roll it back."""


def split_total(rng, total, parts):
    """`total` split into `parts` non-negative ints that add up to it exactly.

    Each part gets its weighted share, rounded down. The rest goes to random
    parts, so no period is far from the others.
    """
    if parts <= 0:
        return []
    weights = [rng.uniform(0.75, 1.25) for _ in range(parts)]
    split = [int(total * weight / sum(weights)) for weight in weights]
    for index in rng.choices(range(parts), weights=weights, k=total - sum(split)):
        split[index] += 1
    return split


def counts_sets(sport):
    """True when the final score is sets won, not points."""
    return (
        sport.period_label.strip().lower() in ("set", "sets")
        or sport.name.strip().lower() == "volleyball"
    )


def _key(name):
    return name.strip().lower()


def classify(event_types):
    """(scoring type or None, assist type or None, other types)."""
    scoring = next((t for t in event_types if _key(t.name) in SCORING_NAMES), None)
    assist = next((t for t in event_types if _key(t.name) in ASSIST_NAMES), None)
    others = [t for t in event_types if t not in (scoring, assist)]
    return scoring, assist, others


def scoring_plays(rng, sport, total):
    """The score as plays: baskets of 1-3 points in basketball, else goals of 1."""
    if _key(sport.name) != "basketball":
        return [1] * total
    plays = []
    while total > 0:
        play = min(rng.choice([2, 2, 2, 3, 1]), total)
        plays.append(play)
        total -= play
    return plays


def other_value(rng, sport, event_type):
    name = _key(event_type.name)
    if any(word in name for word in RARE_WORDS):
        return 1 if rng.random() < 0.1 else 0
    high = 6 if _key(sport.name) == "basketball" else 2
    return rng.randint(0, high)


def team_stats(rng, sport, team_id, players, score, types):
    """{(team_id, player_id, event_type_id): value} for one team."""
    scoring, assist, others = types
    stats = Counter()
    if score is not None:
        weights = [rng.uniform(0.5, 2.0) for _ in players]
        for play in scoring_plays(rng, sport, score):
            scorer = rng.choices(players, weights=weights)[0]
            if scoring:
                stats[(team_id, scorer, scoring.pk)] += play
            helpers = [player for player in players if player != scorer]
            if assist and helpers and rng.random() < ASSIST_SHARE:
                stats[(team_id, rng.choice(helpers), assist.pk)] += 1
    elif assist:
        others = [assist] + others
    for player in players:
        for event_type in others:
            value = other_value(rng, sport, event_type)
            if value:
                stats[(team_id, player, event_type.pk)] += value
    return dict(stats)


def plan_match(rng, match, roster, event_types):
    """The save_match_sheet arguments for one match."""
    sport = match.home_team.sport
    sets = counts_sets(sport)
    types = classify(event_types)
    finals = {
        match.home_team_id: match.home_score,
        match.away_team_id: match.away_score,
    }
    # Draw appearances first, so they don't depend on the event types.
    lineups = {}
    for team_id in (match.home_team_id, match.away_team_id):
        players = sorted(roster[team_id])
        if len(players) >= 3 and rng.random() < 0.5:
            players.remove(rng.choice(players))
        lineups[team_id] = players
    played = {(team, player) for team, players in lineups.items() for player in players}
    stats = {}
    for team_id, players in lineups.items():
        score = None if sets else finals[team_id]
        stats.update(team_stats(rng, sport, team_id, players, score, types))
    periods = []
    if not sets and sport.period_count:
        home = split_total(rng, match.home_score, sport.period_count)
        away = split_total(rng, match.away_score, sport.period_count)
        periods = [
            (number, h, a) for number, (h, a) in enumerate(zip(home, away), start=1)
        ]
    return {
        "periods": periods,
        "final": (match.home_score, match.away_score),
        "stats": stats,
        "played": played,
        "players": {
            (team_id, player)
            for team_id, members in roster.items()
            for player in members
        },
    }


class Command(BaseCommand):
    help = "Add period scores, appearances and player stats to scored matches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be added and save nothing.",
        )
        parser.add_argument(
            "--season",
            type=int,
            nargs="+",
            metavar="PK",
            help="Only these seasons (by pk). Default: every season.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=0,
            help="Random seed. The same seed gives the same rows. Default 0.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        self.verbosity_high = options["verbosity"] >= 2
        self.verb = "would update" if dry_run else "updated"
        matches = self.matches(options["season"])
        types_by_sport = defaultdict(list)
        for event_type in EventType.objects.order_by("name", "pk"):
            types_by_sport[event_type.sport_id].append(event_type)

        skipped = Counter()
        per_sport = defaultdict(Counter)
        sports = {}
        # Seed rows are not league activity: no notifications, no audit rows.
        with notification_signals.muted(), audit_signals.muted():
            for match in matches:
                reason = self.skip_reason(match)
                if reason:
                    skipped[reason] += 1
                    continue
                sport = match.home_team.sport
                sports[sport.pk] = sport
                result = self.fill(
                    match, types_by_sport[sport.pk], options["seed"], dry_run
                )
                if isinstance(result, str):
                    skipped[result] += 1
                    continue
                per_sport[sport.pk].update(result)

        for sport in sorted(sports.values(), key=lambda s: s.name.lower()):
            self.report_sport(sport, per_sport[sport.pk], types_by_sport[sport.pk])
        updated = sum(counts["matches"] for counts in per_sport.values())
        line = f"{self.verb.capitalize()} {updated} matches."
        if skipped:
            reasons = ", ".join(
                f"{count} {reason}" for reason, count in sorted(skipped.items())
            )
            line += f" Skipped {sum(skipped.values())}: {reasons}."
        self.stdout.write(line)
        if dry_run:
            self.stdout.write("Dry run: nothing saved.")

    def matches(self, season_pks):
        matches = Match.objects.all()
        if season_pks:
            found = set(
                Season.objects.filter(pk__in=season_pks).values_list("pk", flat=True)
            )
            missing = [pk for pk in season_pks if pk not in found]
            if missing:
                raise CommandError(f"No season with pk {missing[0]}.")
            matches = matches.filter(season_id__in=season_pks)
        return (
            matches.select_related("season", "home_team__sport", "away_team")
            .annotate(
                has_periods=Exists(
                    MatchPeriodScore.objects.filter(match=OuterRef("pk"))
                ),
                has_stats=Exists(PlayerStat.objects.filter(match=OuterRef("pk"))),
                has_appearances=Exists(
                    MatchAppearance.objects.filter(match=OuterRef("pk"))
                ),
            )
            .order_by("pk")
        )

    def skip_reason(self, match):
        if match.is_cancelled:
            return SKIP_CANCELLED
        if not match.has_result:
            return SKIP_UNSCORED
        if match.season.state == SeasonState.DRAFT:
            return SKIP_DRAFT
        if match.has_periods or match.has_stats or match.has_appearances:
            return SKIP_DETAILS
        return None

    def fill(self, match, event_types, seed, dry_run):
        """Write one match's details. Return the counts, or a skip reason."""
        roster = {match.home_team_id: [], match.away_team_id: []}
        for team_id, player_id in Roster.objects.filter(
            team_id__in=list(roster)
        ).values_list("team_id", "player_id"):
            roster[team_id].append(player_id)
        if not all(roster.values()):
            return SKIP_NO_PLAYERS
        rng = random.Random(f"{seed}:{match.pk}")
        plan = plan_match(rng, match, roster, event_types)
        final = (match.home_score, match.away_score)
        try:
            with transaction.atomic():
                save_match_sheet(match, allow_closed=True, **plan)
                if (match.home_score, match.away_score) != final:
                    raise ValidationError("The final score would change.")
                if dry_run:
                    raise _DryRun
        except _DryRun:
            pass
        except ValidationError as error:
            match.home_score, match.away_score = final
            return f"refused ({' '.join(error.messages)})"
        if self.verbosity_high:
            self.stdout.write(
                f"Match {match.pk} ({match}): {len(plan['periods'])} periods, "
                f"{len(plan['played'])} appearances, {len(plan['stats'])} stats."
            )
        return Counter(
            matches=1,
            periods=len(plan["periods"]),
            appearances=len(plan["played"]),
            stats=len(plan["stats"]),
        )

    def report_sport(self, sport, counts, event_types):
        self.stdout.write(
            f"{sport.name}: {self.verb} {counts['matches']} matches "
            f"({counts['periods']} period scores, {counts['appearances']} "
            f"appearances, {counts['stats']} player stats)."
        )
        sets = counts_sets(sport)
        if not event_types:
            recorded = "appearances" if sets else "periods and appearances"
            self.stdout.write(
                f"{sport.name}: no event types; recorded {recorded} only."
            )
        if sets:
            self.stdout.write(
                f"{sport.name}: the final score counts sets won, so no period "
                "scores and no scoring stat; set points can't add up to it."
            )
        elif event_types and classify(event_types)[0] is None:
            self.stdout.write(
                f"{sport.name}: no scoring event type (Goal or Points); "
                "the other stats only."
            )
