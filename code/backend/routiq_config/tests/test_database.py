"""Database configuration tests that do not establish database connections."""

from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured

from routiq_config.database import database_config_from_url, select_default_database


class DatabaseConfigurationTests(TestCase):
    def test_unset_database_url_keeps_sqlite_fallback(self):
        sqlite_config = {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "local.sqlite3",
        }

        selected = select_default_database("", sqlite_config)
        self.assertIs(selected, sqlite_config)
        self.assertEqual(selected["ENGINE"], "django.db.backends.sqlite3")

    @patch("routiq_config.database.find_spec", return_value=object())
    @patch("dj_database_url.parse")
    def test_postgres_url_enforces_ssl_and_connection_settings(self, parse, _find_spec):
        parse.return_value = {
            "ENGINE": "django.db.backends.postgresql",
            "OPTIONS": {"sslmode": "disable"},
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }

        fallback = {"ENGINE": "django.db.backends.sqlite3", "NAME": "local.sqlite3"}
        config = select_default_database(
            "postgresql://test-user:test-password@session.pooler.supabase.com:5432/postgres",
            fallback,
        )

        parse.assert_called_once_with(
            "postgresql://test-user:test-password@session.pooler.supabase.com:5432/postgres",
            conn_max_age=60,
            conn_health_checks=True,
            ssl_require=True,
        )
        self.assertIsNot(config, fallback)
        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["OPTIONS"]["sslmode"], "require")
        self.assertEqual(config["OPTIONS"]["connect_timeout"], 10)
        self.assertEqual(config["CONN_MAX_AGE"], 60)
        self.assertTrue(config["CONN_HEALTH_CHECKS"])

    @patch("routiq_config.database.find_spec", return_value=object())
    @patch("dj_database_url.parse")
    def test_non_postgres_url_is_rejected(self, parse, _find_spec):
        parse.return_value = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}

        with self.assertRaisesRegex(ImproperlyConfigured, "must use PostgreSQL"):
            database_config_from_url("sqlite:///local.sqlite3")

    @patch("routiq_config.database.find_spec", return_value=None)
    def test_missing_postgres_driver_has_actionable_error(self, _find_spec):
        with self.assertRaisesRegex(ImproperlyConfigured, "psycopg2-binary or psycopg"):
            database_config_from_url("postgresql://user:password@host.example/postgres")

    @patch("routiq_config.database.find_spec", return_value=object())
    @patch("dj_database_url.parse", side_effect=ValueError("private-password-in-parser-error"))
    def test_invalid_url_error_does_not_expose_parser_details(self, _parse, _find_spec):
        with self.assertRaises(ImproperlyConfigured) as raised:
            database_config_from_url("postgresql://test-user:test-password@host.example/postgres")

        self.assertNotIn("private-password", str(raised.exception))
        self.assertNotIn("test-password", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
