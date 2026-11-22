"""Tests for the migration runner, db.migrate."""

import os
import shutil

import pytest

import db


def _folder_with(tmp_path, extra):
    """A copy of the real migrations plus extra {file name: SQL}."""
    for name in os.listdir(db.MIGRATIONS_DIR):
        shutil.copy(os.path.join(db.MIGRATIONS_DIR, name), tmp_path)
    for name, sql in extra.items():
        (tmp_path / name).write_text(sql)
    return str(tmp_path)


def test_applied_migrations_are_recorded(test_db):
    versions = [row["version"] for row in
                test_db.execute("SELECT version FROM schema_migrations").fetchall()]
    assert "001_init.sql" in versions


def test_second_start_applies_nothing():
    assert db.migrate() == []


def test_new_migration_runs_once_and_keeps_existing_rows(tmp_path, test_db):
    test_db.execute(
        "INSERT INTO trips (name, destination, start_date, end_date, capacity)"
        " VALUES ('Andorra', 'Grandvalira', '2027-01-20', '2027-01-24', 10)"
    )
    test_db.commit()
    folder = _folder_with(tmp_path, {
        "900_add_test_note.sql":
            "ALTER TABLE trips ADD test_note NVARCHAR(50) NOT NULL"
            " CONSTRAINT df_trips_test_note DEFAULT 'none';",
    })

    try:
        assert db.migrate(folder) == ["900_add_test_note.sql"]
        assert db.migrate(folder) == []

        row = test_db.execute("SELECT name, test_note FROM trips").fetchone()
        assert row["name"] == "Andorra"
        assert row["test_note"] == "none"
    finally:
        # Undo, so the other tests see the real schema.
        test_db.execute("ALTER TABLE trips DROP CONSTRAINT df_trips_test_note")
        test_db.execute("ALTER TABLE trips DROP COLUMN test_note")
        test_db.execute("DELETE FROM schema_migrations WHERE version = '900_add_test_note.sql'")
        test_db.commit()


def test_failed_migration_is_rolled_back_and_not_recorded(tmp_path, test_db):
    folder = _folder_with(tmp_path, {
        "901_broken.sql": "CREATE TABLE half_done (id INT); SELECT * FROM no_such_table;",
    })

    with pytest.raises(Exception):
        db.migrate(folder)

    assert test_db.execute("SELECT OBJECT_ID('half_done') AS id").fetchone()["id"] is None
    recorded = test_db.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version = '901_broken.sql'"
    ).fetchone()[0]
    assert recorded == 0


def test_missing_database_url_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(db.config, "DATABASE_URL", None)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        db.get_connection()
