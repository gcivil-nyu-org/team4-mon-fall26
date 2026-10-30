from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from teams.catalog_rules import (
    group_legacy_sports,
    name_key,
    normalize_name,
    validate_catalog_name,
)


class CatalogRulesTests(SimpleTestCase):
    def test_normalize_name(self):
        self.assertEqual(normalize_name("  Ultimate \t Frisbee "), "Ultimate Frisbee")

    def test_name_key_ignores_case_and_spacing(self):
        self.assertEqual(name_key("ultimate  frisbee"), name_key(" Ultimate Frisbee"))

    def test_validate_catalog_name(self):
        self.assertEqual(validate_catalog_name("  Soccer "), "Soccer")
        with self.assertRaisesMessage(ValidationError, "Enter a name."):
            validate_catalog_name("   ")
        with self.assertRaisesMessage(ValidationError, "Use 50 characters or fewer."):
            validate_catalog_name("x" * 51)
        self.assertEqual(validate_catalog_name("x" * 50), "x" * 50)

    def test_group_legacy_sports_most_common_spelling(self):
        self.assertEqual(
            group_legacy_sports(["soccer", "Soccer", "soccer", "Basketball"]),
            {"soccer": "soccer", "basketball": "Basketball"},
        )

    def test_group_legacy_sports_tie_is_deterministic(self):
        self.assertEqual(
            group_legacy_sports(["soccer", "Soccer"]), {"soccer": "Soccer"}
        )
        self.assertEqual(
            group_legacy_sports(["Soccer", "soccer"]), {"soccer": "Soccer"}
        )

    def test_group_legacy_sports_skips_blank(self):
        self.assertEqual(
            group_legacy_sports(["", "  ", "Tennis"]), {"tennis": "Tennis"}
        )
