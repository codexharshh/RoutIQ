"""Helpers for selecting a safe Django database configuration."""

from importlib.util import find_spec

from django.core.exceptions import ImproperlyConfigured


def select_default_database(database_url: str, fallback_config: dict) -> dict:
    """Use PostgreSQL when configured and otherwise preserve the given default."""
    if not database_url or not database_url.strip():
        return fallback_config
    return database_config_from_url(database_url)


def database_config_from_url(database_url: str) -> dict:
    """Parse a PostgreSQL URL without connecting to the configured database."""
    if not database_url or not database_url.strip():
        raise ImproperlyConfigured("DATABASE_URL must not be empty.")

    if find_spec("psycopg") is None and find_spec("psycopg2") is None:
        raise ImproperlyConfigured(
            "DATABASE_URL requires the PostgreSQL driver package psycopg2-binary or psycopg."
        )

    try:
        import dj_database_url

        config = dj_database_url.parse(
            database_url.strip(),
            conn_max_age=60,
            conn_health_checks=True,
            ssl_require=True,
        )
    except (ImportError, TypeError, ValueError):
        raise ImproperlyConfigured(
            "DATABASE_URL is invalid or unsupported; use a PostgreSQL Session Pooler URL."
        ) from None

    if config.get("ENGINE") != "django.db.backends.postgresql":
        raise ImproperlyConfigured(
            "DATABASE_URL must use PostgreSQL; SQLite remains the default when it is unset."
        )

    options = config.setdefault("OPTIONS", {})
    # Do not permit URL query parameters to disable TLS for the cloud connection.
    options["sslmode"] = "require"
    options.setdefault("connect_timeout", 10)
    return config
