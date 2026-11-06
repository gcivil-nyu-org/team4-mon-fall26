"""Choose the database from the environment.

Deployed sites set DATABASE_URL to a persistent database. Local development
leaves it unset and uses SQLite. Setup steps: docs/DATABASE.md.
"""

import dj_database_url


def database_config(database_url, sqlite_path):
    """Return Django's settings for the "default" database."""
    if database_url:
        return dj_database_url.parse(
            database_url,
            # Reuse connections between requests, and replace any that dropped.
            conn_max_age=60,
            conn_health_checks=True,
        )
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": sqlite_path,
        # Start write transactions with the write lock held. SQLite ignores
        # select_for_update, so without this two requests can read the same
        # roster and the loser fails with "database is locked" instead of seeing
        # the normal validation message.
        "OPTIONS": {"transaction_mode": "IMMEDIATE"},
    }
