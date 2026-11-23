from django.test import SimpleTestCase

from .naming import clean_city_name


class CleanCityNameTests(SimpleTestCase):
    def test_raw_sizes_get_plain_labels(self):
        cases = {
            "Asser Levy Playground – 45-146ft W x 75-294ft L 1": (
                "Asser Levy Playground – Small soccer field 1"
            ),
            "Chelsea Park – 147-295ft W x 295-393ft L 1": (
                "Chelsea Park – Full-size soccer field 1"
            ),
            "James J Walker Park – 45-146ft W x 75-294ft L 1A": (
                "James J Walker Park – Small soccer field 1A"
            ),
            "Corlears Hook Park – 180 L x 100 W 1": (
                "Corlears Hook Park – Small soccer field 1"
            ),
            "Sara D. Roosevelt Park – 180 (L) x 110 (W) - 6 YD Box and Circle 2": (
                "Sara D. Roosevelt Park – Small soccer field 2"
            ),
            "Chelsea Park – 60ft base path, 150-200ft fence 2": (
                "Chelsea Park – Softball field 2"
            ),
            "Wald Playground – 45-60ft base path, less than 150ft fence 1": (
                "Wald Playground – Softball field 1"
            ),
        }
        for raw, clean in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_city_name(raw, "Soccer"), clean)

    def test_unknown_uses_the_sport(self):
        self.assertEqual(
            clean_city_name("James J Walker Park – Unknown 1", "Pickleball"),
            "James J Walker Park – Pickleball court 1",
        )
        self.assertEqual(
            clean_city_name("East River Park – Unknown 2", "Soccer; Ultimate frisbee"),
            "East River Park – Soccer field 2",
        )
        self.assertEqual(
            clean_city_name("East River Park – Unknown 2", "Tennis"),
            "East River Park – Unknown 2",
        )

    def test_clean_names_stay_as_they_are(self):
        for name in (
            "ABC Playground – Half Court 1",
            "Asser Levy Playground – Volleyball 1",
            "Pier Field – Soccer",
            "Paulson Center",
            "",
        ):
            with self.subTest(name=name):
                self.assertEqual(clean_city_name(name, "Basketball"), name)
