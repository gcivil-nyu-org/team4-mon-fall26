"""Create the default semester seasons for one sport.

seed_semester_seasons calls this for every sport on each deploy. The Sports page
and the Django admin call it when a League Admin adds a sport.
"""

import datetime

from django.db import transaction

from .models import Division, Season
from .season_rules import SeasonState
from .semesters import current_semester, next_semester

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

# Weeks of team registration after the semester start, for new seasons.
REGISTRATION_WEEKS = 3


def default_registration_close(semester, today):
    """The registration close date for a new season, or None if it is past."""
    closes = semester.start_date + datetime.timedelta(weeks=REGISTRATION_WEEKS)
    return closes if closes >= today else None


def ensure_season(sport, semester, state, today):
    """Create the season and its divisions if missing. Return the new season, or None."""
    with transaction.atomic():
        season, made = Season.objects.get_or_create(
            sport=sport,
            term=semester.term,
            defaults={
                "name": f"{semester.label} {sport.name}",
                "start_date": semester.start_date,
                "end_date": semester.end_date,
                "registration_closes_on": default_registration_close(semester, today),
                "state": state,
            },
        )
        if made:
            for name in DEFAULT_DIVISIONS:
                Division(season=season, name=name).save()
    return season if made else None


def ensure_default_seasons(sport, today=None):
    """Make sure `sport` has this semester's season (open) and next (draft).

    Existing seasons are never changed. Return the list of seasons created.
    """
    today = today or datetime.date.today()
    current = current_semester(today)
    created = []
    for semester, state in (
        (current, SeasonState.OPEN),
        (next_semester(current), SeasonState.DRAFT),
    ):
        season = ensure_season(sport, semester, state, today)
        if season is not None:
            created.append(season)
    return created


def created_seasons_message(seasons):
    """The success message for a new sport, naming the seasons it got."""
    if not seasons:
        return "Sport added."
    names = " and ".join(season.name for season in seasons)
    noun = "season" if len(seasons) == 1 else "seasons"
    return f"Sport added with {names} {noun}."
