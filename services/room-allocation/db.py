"""Connections to this service's own SQL Server database, and its migrations.

The service reads one setting, DATABASE_URL, for example
    mssql://rooms_app:<password>@sqlserver:1433/rooms
Characters such as @ / : in the password must be percent-encoded.
"""

import logging
import os
import re
import time
from datetime import date, datetime, timezone
from urllib.parse import unquote, urlsplit

import pymssql

import config

log = logging.getLogger(__name__)

# migrations/ sits next to this file, wherever the app is run from.
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

# A migration file is a number, an underscore, a name and .sql: 002_add_x.sql.
MIGRATION_NAME = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")


class Row(dict):
    """A result row read by column name, row["name"], or position, row[0].

    Dates come back as ISO strings ("2027-01-15"), and times as UTC ISO
    strings ending in +00:00, the same values the SQLite version returned,
    so the API and the UI see no difference.
    """

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _to_json_value(value):
    if isinstance(value, datetime):
        # DATETIME2 has no time zone; this app only ever stores UTC.
        return value.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class Cursor:
    """The result of Connection.execute: fetchone, fetchall and rowcount.

    All rows are read straight away. A connection can only run one query
    at a time, so a result left unread would block the next statement
    (for example a SELECT that only takes a lock).
    """

    def __init__(self, cursor):
        self.rowcount = cursor.rowcount
        if cursor.description is None:
            self._rows = []
        else:
            names = [column[0] for column in cursor.description]
            self._rows = [Row(zip(names, map(_to_json_value, values)))
                          for values in cursor.fetchall()]

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows


class Connection:
    """A pymssql connection with the small execute() API the domain code uses.

    Queries are written with ? placeholders, as they were for SQLite;
    execute() turns them into the %s placeholders pymssql expects. A
    transaction starts with the first statement and ends at commit() or
    rollback().
    """

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        cursor = self._raw.cursor()
        cursor.execute(sql.replace("?", "%s"), tuple(params))
        return Cursor(cursor)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


def _connect_args(url):
    """Split DATABASE_URL into the arguments pymssql.connect takes."""
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    parts = urlsplit(url)
    return {
        "server": parts.hostname,
        "port": parts.port or 1433,
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": parts.path.lstrip("/"),
    }


def get_connection(attempts=3):
    """Open a connection, retrying with a growing wait if the server is not ready.

    On Azure the serverless database pauses when idle and refuses
    connections for up to about a minute while it resumes (error 40613),
    so a failed connect is tried again after 1 s, 2 s, 4 s, ...
    """
    args = _connect_args(config.DATABASE_URL)
    wait = 1
    for attempt in range(1, attempts + 1):
        try:
            raw = pymssql.connect(**args, login_timeout=10, timeout=30, autocommit=False)
            return Connection(raw)
        except (pymssql.OperationalError, pymssql.InterfaceError):
            if attempt == attempts:
                raise
            log.warning("Database not reachable (attempt %d of %d), retrying in %d s",
                        attempt, attempts, wait)
            time.sleep(wait)
            wait = min(wait * 2, 15)


def migrate(folder=MIGRATIONS_DIR):
    """Apply, in order, every migration in folder that has not been applied.

    Each applied file is recorded in schema_migrations, so it runs exactly
    once: a second start applies nothing. A migration and its record are
    committed together, so a failing migration leaves no half-applied
    change and is tried again on the next start. Returns the files applied.

    Only one replica runs at a time (maximum replicas 1), so two copies of
    this never run at once.
    """
    # At startup the database may be resuming from pause, so wait longer.
    conn = get_connection(attempts=8)
    try:
        conn.execute(
            """
            IF OBJECT_ID('schema_migrations', 'U') IS NULL
            CREATE TABLE schema_migrations (
                version    NVARCHAR(255) PRIMARY KEY,
                applied_at DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
            )
            """
        )
        conn.commit()

        done = {row["version"] for row in
                conn.execute("SELECT version FROM schema_migrations").fetchall()}
        files = sorted(name for name in os.listdir(folder) if MIGRATION_NAME.match(name))

        applied = []
        for name in files:
            if name in done:
                continue
            with open(os.path.join(folder, name)) as migration:
                sql = migration.read()
            log.info("Applying migration %s", name)
            try:
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (name,))
                conn.commit()
            except Exception:
                conn.rollback()
                log.error("Migration %s failed and was rolled back", name)
                raise
            applied.append(name)

        log.info("Database up to date: %d migration(s) applied now, %d in total",
                 len(applied), len(done) + len(applied))
        return applied
    finally:
        conn.close()


def check_health():
    """True if this service can read and write its own database right now.

    It reads schema_migrations and makes a real write to it inside a
    transaction that is then rolled back, so nothing changes. Only one
    connection attempt: a health check must answer quickly.
    """
    try:
        conn = get_connection(attempts=1)
    except Exception:
        log.warning("Health check: cannot connect to the database")
        return False
    try:
        conn.execute("SELECT TOP 1 version FROM schema_migrations").fetchone()
        conn.execute(
            "UPDATE schema_migrations SET applied_at = applied_at"
            " WHERE version = (SELECT MIN(version) FROM schema_migrations)"
        )
        return True
    except Exception:
        log.warning("Health check: cannot read or write the database")
        return False
    finally:
        conn.rollback()
        conn.close()
