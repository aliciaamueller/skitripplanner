"""Tests for the migration runner, db.migrate."""

import db


def test_applied_migrations_are_recorded(test_db):
    versions = [row["version"] for row in
                test_db.execute("SELECT version FROM schema_migrations").fetchall()]
    assert "001_init.sql" in versions


def test_second_start_applies_nothing():
    assert db.migrate() == []
