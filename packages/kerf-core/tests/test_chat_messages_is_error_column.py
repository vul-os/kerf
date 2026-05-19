"""Regression: chat_messages.is_error column is present in baseline migration.

Bug: when a tool call failed server-side the dispatcher had no column to
persist the failure flag, so the LLM never saw is_error=True in the
history replayed to it on the next turn.

Fix: is_error BOOLEAN NOT NULL DEFAULT FALSE was folded into the
chat_messages CREATE TABLE in 0001_core_identity.sql per the
"clean baseline migrations" rule — NOT via an ALTER TABLE shim.

This test pins the DDL so a future refactor cannot silently remove the
column (the dispatcher INSERT and the _load_llm_history SELECT both
reference it and would 500 if it disappeared).
"""
import pathlib
import re

_BASELINE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/kerf_core/db/migrations/0001_core_identity.sql"
).read_text()


def _table_block(table: str) -> str:
    m = re.search(
        rf"create table if not exists {re.escape(table)} \((.+?)\);",
        _BASELINE, re.S | re.I,
    )
    assert m, f"{table} CREATE TABLE not found in baseline"
    return m.group(1)


def test_chat_messages_has_is_error_column():
    body = _table_block("chat_messages")
    assert re.search(
        r"is_error\s+boolean\s+not\s+null\s+default\s+false",
        body, re.I,
    ), (
        "chat_messages.is_error BOOLEAN NOT NULL DEFAULT FALSE must be "
        "present in the baseline CREATE TABLE"
    )


def test_no_alter_table_add_column_shim_for_is_error():
    """is_error must be folded into CREATE TABLE; never an ALTER TABLE shim."""
    forbidden_pat = re.compile(
        r"alter\s+table\s+chat_messages\s+add\s+column[^;]{0,80}?\bis_error\b",
        re.I | re.S,
    )
    migrations_dir = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src/kerf_core/db/migrations"
    )
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        text = sql_file.read_text()
        match = forbidden_pat.search(text)
        assert match is None, (
            f"{sql_file.name} contains ALTER TABLE chat_messages ADD COLUMN "
            f"is_error — fold it into the baseline CREATE TABLE instead."
        )
