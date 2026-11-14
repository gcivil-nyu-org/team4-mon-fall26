import datetime
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from .management.commands.seed_semester_seasons import (
    DEFAULT_DIVISIONS,
    current_semester,
    next_semester,
)
from .models import Division, Season, Sport
from .season_rules import SeasonState


def seed(today="2026-11-13"):
    out = StringIO()
    call_command("seed_semester_seasons", "--today", today, stdout=out)
    return out.getvalue().strip()


def terms(today):
    current = current_semester(datetime.date.fromisoformat(today))
    return current.term, next_semester(current).term


class SemesterDateTests(SimpleTestCase):
    def test_mid_fall(self):
        self.assertEqual(terms("2026-11-13"), ("2026-fall", "2027-spring"))

    def test_mid_spring(self):
        self.assertEqual(terms("2027-03-01"), ("2027-spring", "2027-fall"))

    def test_semester_edges_are_inside(self):
        self.assertEqual(terms("2026-09-01")[0], "2026-fall")
        self.assertEqual(terms("2026-12-15")[0], "2026-fall")
        self.assertEqual(terms("2027-01-20")[0], "2027-spring")
        self.assertEqual(terms("2027-05-10")[0], "2027-spring")

    def test_winter_gap_picks_next_spring(self):
        self.assertEqual(terms("2026-12-16"), ("2027-spring", "2027-fall"))
        self.assertEqual(terms("2027-01-01"), ("2027-spring", "2027-fall"))
        self.assertEqual(terms("2027-01-19"), ("2027-spring", "2027-fall"))

    def test_summer_gap_picks_next_fall(self):
        self.assertEqual(terms("2027-05-11"), ("2027-fall", "2028-spring"))
        self.assertEqual(terms("2027-08-31"), ("2027-fall", "2028-spring"))

    def test_semester_dates(self):
        fall = current_semester(datetime.date(2026, 10, 1))
        self.assertEqual(
            (fall.label, fall.start_date, fall.end_date),
            ("Fall 2026", datetime.date(2026, 9, 1), datetime.date(2026, 12, 15)),
        )
        spring = next_semester(fall)
        self.assertEqual(
            (spring.label, spring.start_date, spring.end_date),
            ("Spring 2027", datetime.date(2027, 1, 20), datetime.date(2027, 5, 10)),
        )


class SeedSemesterSeasonsTests(TestCase):
    def setUp(self):
        self.basketball = Sport.objects.create(name="Basketball")
        self.soccer = Sport.objects.create(name="Soccer")

    def test_already_there_counts_seasons_that_exist(self):
        seed()
        Season.objects.filter(sport=self.soccer, term="2027-spring").delete()
        self.assertEqual(seed(), "Semester seasons: 1 created, 3 already there.")

    def test_creates_open_current_and_draft_next_per_sport(self):
        self.assertEqual(seed(), "Semester seasons: 4 created, 0 already there.")
        self.assertEqual(
            set(Season.objects.values_list("name", "term", "state", "sport__name")),
            {
                ("Fall 2026 Basketball", "2026-fall", SeasonState.OPEN, "Basketball"),
                ("Fall 2026 Soccer", "2026-fall", SeasonState.OPEN, "Soccer"),
                (
                    "Spring 2027 Basketball",
                    "2027-spring",
                    SeasonState.DRAFT,
                    "Basketball",
                ),
                ("Spring 2027 Soccer", "2027-spring", SeasonState.DRAFT, "Soccer"),
            },
        )
        season = Season.objects.get(name="Spring 2027 Soccer")
        self.assertEqual(
            (season.start_date, season.end_date),
            (datetime.date(2027, 1, 20), datetime.date(2027, 5, 10)),
        )

    def test_new_seasons_get_the_default_divisions(self):
        seed()
        for season in Season.objects.all():
            self.assertEqual(
                sorted(season.divisions.values_list("name", flat=True)),
                sorted(DEFAULT_DIVISIONS),
            )

    def test_second_run_creates_nothing(self):
        seed()
        self.assertEqual(seed(), "Semester seasons: 0 created, 4 already there.")
        self.assertEqual(Season.objects.count(), 4)
        self.assertEqual(Division.objects.count(), 4 * len(DEFAULT_DIVISIONS))

    def test_existing_season_is_left_alone(self):
        seed()
        season = Season.objects.get(sport=self.soccer, term="2026-fall")
        season.name = "Soccer league"
        season.state = SeasonState.ACTIVE
        season.end_date = datetime.date(2026, 12, 1)
        season.save()
        season.divisions.exclude(name="CAS").delete()

        seed()
        season.refresh_from_db()
        self.assertEqual(
            (season.name, season.state, season.end_date),
            ("Soccer league", SeasonState.ACTIVE, datetime.date(2026, 12, 1)),
        )
        self.assertEqual(list(season.divisions.values_list("name", flat=True)), ["CAS"])

    def test_sport_added_later_gets_seasons_on_next_run(self):
        seed()
        Sport.objects.create(name="Volleyball")
        self.assertEqual(seed(), "Semester seasons: 2 created, 4 already there.")
        self.assertEqual(
            set(
                Season.objects.filter(sport__name="Volleyball").values_list(
                    "term", "state"
                )
            ),
            {("2026-fall", SeasonState.OPEN), ("2027-spring", SeasonState.DRAFT)},
        )

    def test_next_semester_moves_with_today(self):
        seed("2026-11-13")
        seed("2027-02-01")
        self.assertEqual(
            set(Season.objects.filter(sport=self.soccer).values_list("term", "state")),
            {
                ("2026-fall", SeasonState.OPEN),
                ("2027-spring", SeasonState.DRAFT),
                ("2027-fall", SeasonState.DRAFT),
            },
        )

    def test_custom_season_without_term_is_ignored(self):
        Season.objects.create(
            name="Fall 2026 Basketball", start_date="2026-09-01", sport=self.basketball
        )
        self.assertEqual(seed(), "Semester seasons: 4 created, 0 already there.")

    def test_no_sports_creates_nothing(self):
        Sport.objects.all().delete()
        self.assertEqual(seed(), "Semester seasons: 0 created, 0 already there.")

    def test_bad_today_is_an_error(self):
        with self.assertRaises(CommandError):
            seed("13/11/2026")
