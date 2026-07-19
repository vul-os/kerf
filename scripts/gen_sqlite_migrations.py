#!/usr/bin/env python3
"""Generate the checked-in SQLite migration set from the Postgres baseline.

kerf's schema of record is the Postgres migration set in
``packages/kerf-core/src/kerf_core/db/migrations/*.sql``.  The embedded SQLite
backend needs the *same* schema expressed in SQLite DDL.  Rather than translate
DDL at runtime (fragile, and it would re-run on every boot), we translate it
*once, offline* with this script and check the output into
``packages/kerf-core/src/kerf_core/db/migrations_sqlite/``.

Run it whenever a Postgres migration changes::

    python scripts/gen_sqlite_migrations.py

Translation rules (DDL only — query-level translation lives in
``kerf_core.db.dialect``):

  * ``create extension …``            -> dropped
  * ``gen_random_uuid()``             -> pure-SQLite UUIDv4 expression (default)
  * ``uuid`` / ``citext`` / ``jsonb`` -> ``text`` (citext -> ``text collate nocase``)
  * ``timestamptz`` / ``timestamp``   -> ``text``  (ISO-8601 / CURRENT_TIMESTAMP)
  * ``bytea``                         -> ``blob``
  * ``<type>[]`` (arrays)             -> ``text``  (stored as JSON)
  * ``serial`` / ``bigserial``        -> ``integer``
  * ``now()``                         -> ``CURRENT_TIMESTAMP``
  * ``::type`` casts in defaults      -> removed  (``'{}'::jsonb`` -> ``'{}'``)
  * ``… using gin/gist (…)`` indexes  -> dropped   (no JSON/array index in SQLite)
  * everything else (checks, inline FKs, partial ``where`` indexes, composite
    PKs) is already valid SQLite and passes through unchanged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent / "packages" / "kerf-core" / "src" / "kerf_core" / "db"
_SRC_DIR = _PKG / "migrations"
_OUT_DIR = _PKG / "migrations_sqlite"

# Keep in lock-step with kerf_core.db.dialect.SQLITE_UUID4_EXPR.
_UUID4 = (
    "(lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || "
    "substr(lower(hex(randomblob(2))),2) || '-' || "
    "substr('89ab',abs(random())%4+1,1) || "
    "substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))))"
)

_RE_EXTENSION = re.compile(r"^\s*create\s+extension\b.*$", re.IGNORECASE)
_RE_GIN = re.compile(r"\busing\s+(gin|gist)\b", re.IGNORECASE)
_RE_GEN_UUID = re.compile(r"gen_random_uuid\s*\(\s*\)", re.IGNORECASE)
# `now() + interval '24 hours'` / `now() - interval 'N unit'` ->
# `(datetime('now','+24 hours'))` — SQLite has no INTERVAL literal.
_RE_NOW_INTERVAL = re.compile(
    r"now\s*\(\s*\)\s*([+-])\s*interval\s*'([^']+)'", re.IGNORECASE)
_RE_NOW = re.compile(r"\bnow\s*\(\s*\)", re.IGNORECASE)
_RE_CAST = re.compile(r"::\s*[A-Za-z_][A-Za-z0-9_]*(\s*\[\s*\])?")
_RE_ARRAY = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*\]")

# type-token replacements (word-boundary, case-insensitive)
_TYPE_SUBS = [
    (re.compile(r"\bcitext\b", re.IGNORECASE), "text collate nocase"),
    (re.compile(r"\btimestamptz\b", re.IGNORECASE), "text"),
    (re.compile(r"\btimestamp\s+with\s+time\s+zone\b", re.IGNORECASE), "text"),
    (re.compile(r"\btimestamp\b", re.IGNORECASE), "text"),
    (re.compile(r"\bjsonb\b", re.IGNORECASE), "text"),
    (re.compile(r"\bbytea\b", re.IGNORECASE), "blob"),
    (re.compile(r"\bbigserial\b", re.IGNORECASE), "integer"),
    (re.compile(r"\bserial\b", re.IGNORECASE), "integer"),
    (re.compile(r"\buuid\b", re.IGNORECASE), "text"),
]


def translate_ddl(sql: str) -> str:
    out_lines: list[str] = []
    for line in sql.splitlines():
        if _RE_EXTENSION.match(line):
            continue
        # Drop GIN/GiST index statements (single-line in the baseline).
        if _RE_GIN.search(line):
            continue
        # gen_random_uuid() before the \buuid\b type sub so the expression body
        # (which contains no 'uuid') is not itself rewritten.
        line = _RE_GEN_UUID.sub(_UUID4, line)
        line = _RE_NOW_INTERVAL.sub(
            lambda m: f"(datetime('now','{m.group(1)}{m.group(2)}'))", line)
        line = _RE_NOW.sub("CURRENT_TIMESTAMP", line)
        # Array types -> text (stored as a JSON array).  A Postgres empty-array
        # default `'{}'` must become a JSON empty array `'[]'` so it round-trips
        # through json.loads on read.  Do this before erasing the `[]` marker.
        if _RE_ARRAY.search(line):
            line = re.sub(r"default\s+'\{\}'", "default '[]'", line, flags=re.IGNORECASE)
        line = _RE_ARRAY.sub("text", line)
        for rx, repl in _TYPE_SUBS:
            line = rx.sub(repl, line)
        # Strip ::casts from defaults etc.
        line = _RE_CAST.sub("", line)
        out_lines.append(line)
    return "\n".join(out_lines).rstrip() + "\n"


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(_SRC_DIR.glob("*.sql"))
    header = (
        "-- AUTO-GENERATED from ../migrations/{name} by "
        "scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.\n"
        "-- SQLite dialect of the Postgres baseline for kerf's embedded backend.\n\n"
    )
    for f in files:
        translated = translate_ddl(f.read_text())
        (_OUT_DIR / f.name).write_text(header.format(name=f.name) + translated)
        print(f"  ✓ {f.name}")
    print(f"\n{len(files)} SQLite migrations written to {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
