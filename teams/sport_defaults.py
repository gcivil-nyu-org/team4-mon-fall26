"""Default periods by sport. Migration 0014 keeps a frozen copy, and
test_migration_copy_matches_app_mapping keeps the two copies equal."""

from teams.catalog_rules import name_key

DEFAULT_PERIODS = (4, "Q")

# Keys are name_key(sport name).
SPORT_PERIODS = {
    "basketball": (4, "Q"),
    "soccer": (2, "Half"),
    "futsal": (2, "Half"),
    "volleyball": (5, "Set"),
    "flag football": (4, "Q"),
    "ultimate": (2, "Half"),
    "ultimate frisbee": (2, "Half"),
}


def default_periods(name):
    """(period_count, period_label) for a sport name, else DEFAULT_PERIODS."""
    return SPORT_PERIODS.get(name_key(name or ""), DEFAULT_PERIODS)
