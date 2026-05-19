"""Regression: rate_limit_buckets table is present in baseline 0001 with the
expected primary key and index.

This pins the DDL so a refactor can't silently strip the table or its
index (the rate-limit helper would fail at runtime if either is missing).
"""
import pathlib
import re

_BASELINE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/kerf_core/db/migrations/0001_core_identity.sql"
).read_text()


def test_rate_limit_buckets_table_present():
    """rate_limit_buckets CREATE TABLE must exist in the baseline."""
    assert "create table if not exists rate_limit_buckets" in _BASELINE.lower(), (
        "rate_limit_buckets CREATE TABLE not found in 0001_core_identity.sql"
    )


def test_rate_limit_buckets_has_bucket_key_column():
    m = re.search(
        r"create table if not exists rate_limit_buckets \((.+?)\);",
        _BASELINE,
        re.S | re.I,
    )
    assert m, "rate_limit_buckets CREATE TABLE block not found"
    body = m.group(1)
    assert re.search(r"bucket_key\s+text\s+not null", body, re.I), (
        "rate_limit_buckets.bucket_key text not null column not found"
    )


def test_rate_limit_buckets_has_window_start_column():
    m = re.search(
        r"create table if not exists rate_limit_buckets \((.+?)\);",
        _BASELINE,
        re.S | re.I,
    )
    assert m, "rate_limit_buckets CREATE TABLE block not found"
    body = m.group(1)
    assert re.search(r"window_start\s+timestamptz\s+not null", body, re.I), (
        "rate_limit_buckets.window_start timestamptz not null column not found"
    )


def test_rate_limit_buckets_has_count_column():
    m = re.search(
        r"create table if not exists rate_limit_buckets \((.+?)\);",
        _BASELINE,
        re.S | re.I,
    )
    assert m, "rate_limit_buckets CREATE TABLE block not found"
    body = m.group(1)
    assert re.search(r"count\s+integer\s+not null", body, re.I), (
        "rate_limit_buckets.count integer not null column not found"
    )


def test_rate_limit_buckets_has_composite_pk():
    m = re.search(
        r"create table if not exists rate_limit_buckets \((.+?)\);",
        _BASELINE,
        re.S | re.I,
    )
    assert m, "rate_limit_buckets CREATE TABLE block not found"
    body = m.group(1)
    assert re.search(
        r"primary key\s*\(\s*bucket_key\s*,\s*window_start\s*\)",
        body,
        re.I,
    ), "rate_limit_buckets composite PK (bucket_key, window_start) not found"


def test_rate_limit_buckets_window_idx_present():
    """An index on window_start must exist for GC query performance."""
    assert "rate_limit_buckets_window_idx" in _BASELINE, (
        "rate_limit_buckets_window_idx index not found in 0001_core_identity.sql"
    )


def test_no_alter_table_shim_for_rate_limit_buckets():
    """The table must be created inline — no ALTER TABLE ADD COLUMN shim."""
    forbidden = re.compile(
        r"alter\s+table\s+rate_limit_buckets\s+add\s+column",
        re.I,
    )
    migrations_dir = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src/kerf_core/db/migrations"
    )
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        text = sql_file.read_text()
        m = forbidden.search(text)
        assert m is None, (
            f"{sql_file.name} contains an ALTER TABLE ADD COLUMN shim for "
            f"rate_limit_buckets. Fold the column into CREATE TABLE in "
            f"0001_core_identity.sql instead."
        )
