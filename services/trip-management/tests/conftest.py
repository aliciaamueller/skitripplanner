"""Shared test setup: a throwaway SQL Server database for this service.

The tests need a SQL Server on which they may create a database, given as
TEST_DATABASE_URL with an administrator login, for example
    mssql://sa:<password>@localhost:1433/master
They never use the service's real database: they create trips_test from
scratch, apply the migrations to it with the real runner, and empty its
tables before every test.
"""

import os
from urllib.parse import urlsplit, urlunsplit

import pymssql
import pytest

TEST_DB = "trips_test"
ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
if not ADMIN_URL:
    pytest.exit("Set TEST_DATABASE_URL to a SQL Server admin login, see tests/conftest.py",
                returncode=2)


def _recreate_test_database():
    """Drop trips_test if a previous run left it, and create it empty."""
    parts = urlsplit(ADMIN_URL)
    conn = pymssql.connect(server=parts.hostname, port=parts.port or 1433,
                           user=parts.username, password=parts.password,
                           database="master", autocommit=True)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"IF DB_ID('{TEST_DB}') IS NOT NULL BEGIN "
            f"ALTER DATABASE {TEST_DB} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE {TEST_DB}; END"
        )
        cursor.execute(f"CREATE DATABASE {TEST_DB}")
    finally:
        conn.close()
    return urlunsplit(parts._replace(path="/" + TEST_DB))


# Before config, db or app are imported, so they all use the test database.
os.environ["DATABASE_URL"] = _recreate_test_database()

import db  # noqa: E402

db.migrate()

# Children before parents, so foreign keys never block a delete.
TABLES = ["registrations", "trips"]


@pytest.fixture(autouse=True)
def empty_tables():
    """Start every test with empty tables whose IDs start again at 1."""
    conn = db.get_connection()
    try:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
            # Only reseed a table that has had rows: on a table that never
            # had any, RESEED 0 would make the next ID 0 instead of 1.
            conn.execute(
                f"IF (SELECT last_value FROM sys.identity_columns "
                f"WHERE object_id = OBJECT_ID('{table}')) IS NOT NULL "
                f"DBCC CHECKIDENT ('{table}', RESEED, 0)"
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def test_db():
    """A connection to the test database, for checking rows directly."""
    conn = db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def no_cancellation_listeners(monkeypatch):
    """Start every test with no listeners.

    app.py subscribes a listener that calls Room Allocation over HTTP, so
    without this a cancellation in any test would try to reach the network.
    """
    import trip_management

    monkeypatch.setattr(trip_management, "_cancellation_listeners", [])
