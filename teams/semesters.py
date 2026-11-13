"""Fall and Spring semester dates, shared by the seed command and the dashboard."""

import datetime
from typing import NamedTuple

# (term, label, start (month, day), end (month, day)), in calendar order.
SEMESTERS = [
    ("spring", "Spring", (1, 20), (5, 10)),
    ("fall", "Fall", (9, 1), (12, 15)),
]


class Semester(NamedTuple):
    term: str  # for example "2026-fall"
    label: str  # for example "Fall 2026"
    start_date: datetime.date
    end_date: datetime.date


def semesters_in_year(year):
    """Return the semesters that start in `year`, in calendar order."""
    return [
        Semester(
            term=f"{year}-{key}",
            label=f"{label} {year}",
            start_date=datetime.date(year, *start),
            end_date=datetime.date(year, *end),
        )
        for key, label, start, end in SEMESTERS
    ]


def current_semester(today):
    """Return the semester that contains `today`, or else the next one to start."""
    for semester in semesters_in_year(today.year) + semesters_in_year(today.year + 1):
        if today <= semester.end_date:
            return semester
    raise AssertionError("unreachable: next year always has a semester")


def next_semester(semester):
    """Return the semester that starts after `semester`."""
    return current_semester(semester.end_date + datetime.timedelta(days=1))
