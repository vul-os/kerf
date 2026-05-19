"""Pin: files.version column is folded into the baseline CREATE TABLE.

Regression guard for the OCC feature: `files.version BIGINT NOT NULL DEFAULT 1`
must be part of the CREATE TABLE statement in the baseline migration, NOT added
via an `ALTER TABLE … ADD COLUMN` shim.

Per the "clean baseline migrations" memory note: DBs are reset on deploy, so
ALTER-based shims on the consolidated baseline are forbidden. This test catches
the easy mistake of moving the column to a separate migration.
"""
import pathlib
import re

_BASELINE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/kerf_core/db/migrations/0001_core_identity.sql"
).read_text()


def _files_create_block() -> str:
    """Extract the CREATE TABLE files (...) block."""
    m = re.search(
        r"create table if not exists files \((.+?)\);",
        _BASELINE, re.S | re.I,
    )
    assert m, "files CREATE TABLE not found in baseline 0001_core_identity.sql"
    return m.group(1)


def test_version_column_present_in_files_create_table():
    """files.version must appear inside the CREATE TABLE block."""
    body = _files_create_block()
    assert re.search(r"\bversion\b", body, re.I), (
        "files.version column is missing from CREATE TABLE files in 0001_core_identity.sql. "
        "Fold the column into the table definition, do NOT add it via ALTER TABLE."
    )


def test_version_column_is_bigint():
    """files.version must be declared as BIGINT."""
    body = _files_create_block()
    assert re.search(r"\bversion\s+bigint\b", body, re.I), (
        "files.version must be BIGINT (found but wrong type, or missing) in 0001_core_identity.sql"
    )


def test_version_column_has_not_null():
    """files.version must be NOT NULL."""
    body = _files_create_block()
    assert re.search(r"\bversion\s+bigint\s+not\s+null\b", body, re.I), (
        "files.version must be BIGINT NOT NULL in 0001_core_identity.sql"
    )


def test_version_column_has_default_1():
    """files.version must default to 1."""
    body = _files_create_block()
    assert re.search(r"\bversion\s+bigint\s+not\s+null\s+default\s+1\b", body, re.I), (
        "files.version must be BIGINT NOT NULL DEFAULT 1 in 0001_core_identity.sql"
    )


def test_no_alter_table_add_version_shim():
    """Ensure no ALTER TABLE … ADD COLUMN version shim exists in any migration."""
    migrations_dir = pathlib.Path(__file__).resolve().parents[1] / "src/kerf_core/db/migrations"
    forbidden = re.compile(
        r"alter\s+table\s+files\s+add\s+column.*?\bversion\b",
        re.I | re.S,
    )
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        text = sql_file.read_text()
        m = forbidden.search(text)
        assert m is None, (
            f"{sql_file.name} contains an ALTER TABLE files ADD COLUMN version shim. "
            f"The column must be folded into CREATE TABLE in 0001_core_identity.sql."
        )
