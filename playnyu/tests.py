import logging
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import get_hasher
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


MD5 = "django.contrib.auth.hashers.MD5PasswordHasher"
PBKDF2 = "django.contrib.auth.hashers.PBKDF2PasswordHasher"
# Loads settings in a new process with a chosen sys.argv, then prints the result.
SCRIPT = (
    "import sys; sys.argv = sys.argv[1:]\n"
    "from django.conf import settings\n"
    "print(settings.PASSWORD_HASHERS[0], settings.TESTING)\n"
)


class TestHasherTests(SimpleTestCase):
    def test_test_run_uses_md5(self):
        self.assertTrue(settings.TESTING)
        self.assertEqual(settings.PASSWORD_HASHERS, [MD5])
        self.assertEqual(get_hasher().algorithm, "md5")

    def first_hasher(self, *argv):
        env = {**os.environ, "DJANGO_SETTINGS_MODULE": "playnyu.settings"}
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT, *argv],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.split()

    def test_other_commands_keep_the_default_hasher(self):
        for argv in (
            ["manage.py", "runserver"],
            ["manage.py", "migrate"],
            ["gunicorn", "playnyu.wsgi"],
            ["manage.py", "shell", "test"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self.first_hasher(*argv), [PBKDF2, "False"])

    def test_manage_py_test_sets_the_flag(self):
        self.assertEqual(self.first_hasher("manage.py", "test"), [MD5, "True"])


# Loads settings in a new process with a chosen sys.argv, then prints the
# django.request logger config, or None when the defaults apply.
LOGGING_SCRIPT = (
    "import sys; sys.argv = sys.argv[1:]\n"
    "from django.conf import settings\n"
    "print(settings.LOGGING['loggers'].get('django.request', {}).get('level'))\n"
)


class TestRequestLoggingTests(SimpleTestCase):
    def test_test_run_logs_request_errors_only(self):
        self.assertEqual(logging.getLogger("django.request").level, logging.ERROR)

    def test_assert_logs_still_sees_request_warnings(self):
        with self.assertLogs("django.request", "WARNING") as logs:
            self.client.get("/no-such-page/")
        self.assertIn("Not Found: /no-such-page/", logs.output[0])

    def request_level(self, *argv):
        env = {**os.environ, "DJANGO_SETTINGS_MODULE": "playnyu.settings"}
        result = subprocess.run(
            [sys.executable, "-c", LOGGING_SCRIPT, *argv],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_other_commands_keep_request_warnings(self):
        for argv in (["manage.py", "runserver"], ["gunicorn", "playnyu.wsgi"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.request_level(*argv), "None")
        self.assertEqual(self.request_level("manage.py", "test"), "ERROR")
