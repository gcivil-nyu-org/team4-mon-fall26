from pathlib import Path

from django.test import SimpleTestCase

from playnyu.database import database_config

SQLITE_PATH = Path("/tmp/db.sqlite3")


class DatabaseConfigTests(SimpleTestCase):
    def assert_uses_sqlite(self, config):
        self.assertEqual(config["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(config["NAME"], SQLITE_PATH)
        self.assertEqual(config["OPTIONS"]["transaction_mode"], "IMMEDIATE")

    def test_unset_url_uses_sqlite(self):
        self.assert_uses_sqlite(database_config(None, SQLITE_PATH))

    def test_empty_url_uses_sqlite(self):
        self.assert_uses_sqlite(database_config("", SQLITE_PATH))

    def test_postgres_url_sets_the_connection(self):
        config = database_config(
            "postgres://app:p%40ss%2Fword@db.example.com:5432/playnyu?sslmode=require",
            SQLITE_PATH,
        )
        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "playnyu")
        self.assertEqual(config["USER"], "app")
        self.assertEqual(config["PASSWORD"], "p@ss/word")
        self.assertEqual(config["HOST"], "db.example.com")
        self.assertEqual(config["PORT"], 5432)
        self.assertEqual(config["OPTIONS"]["sslmode"], "require")
        self.assertEqual(config["CONN_MAX_AGE"], 60)
        self.assertTrue(config["CONN_HEALTH_CHECKS"])
