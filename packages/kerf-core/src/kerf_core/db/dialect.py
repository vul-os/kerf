"""Postgres -> SQLite dialect translation for kerf's embedded (zero-dependency) mode.

kerf's query layer is written against asyncpg / PostgreSQL: numbered ``$N``
placeholders, ``jsonb`` casts + ``->>`` extraction, ``= ANY(col)`` array
membership, ``now()``, ``FOR UPDATE SKIP LOCKED`` and so on.  When kerf runs on
the embedded SQLite backend (the default for a local install) the *same* query
strings are re-pointed at SQLite through a thin connection adapter
(:mod:`kerf_core.db.sqlite_backend`).  This module is the translation layer that
sits between the two.

It is deliberately a *runtime query* translator only.  Schema DDL is NOT
translated at runtime — a checked-in SQLite migration set
(``db/migrations_sqlite/``) owns the schema, generated once by
``scripts/gen_sqlite_migrations.py``.  Keeping DDL out of the runtime path means
the small, well-understood set of DML/SELECT-level Postgres-isms below is all we
translate on the hot path.

Translations applied (in order):

  1. ``expr::jsonb->>'k'`` / ``expr->>'k'``  ->  ``json_extract(expr, '$.k')``
  2. ``$N = ANY(col)``                       ->  ``EXISTS (SELECT 1 FROM
                                                 json_each(col) WHERE value = $N)``
  3. ``::type`` casts                        ->  removed (SQLite is dynamically
                                                 typed; ``'{}'::jsonb`` -> ``'{}'``)
  4. ``gen_random_uuid()``                   ->  a pure-SQLite UUIDv4 expression
  5. ``now()`` / ``current_timestamp``       ->  ``CURRENT_TIMESTAMP``
  6. ``FOR UPDATE SKIP LOCKED`` / ``FOR      ->  removed (single-writer embedded
     UPDATE``                                    mode; the enclosing txn suffices)
  7. ``ILIKE``                               ->  ``LIKE`` (SQLite LIKE is
                                                 ASCII-case-insensitive)
  8. ``$N`` placeholders                     ->  ``?`` with positional re-binding
                                                 (handles reuse / out-of-order)

Param + row value adaptation lives here too so the backend adapter stays thin.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import uuid
from typing import Any, Sequence

# ── SQLite scheme detection ────────────────────────────────────────────────────

_SQLITE_SCHEMES = ("sqlite://", "sqlite3://", "file:")


def is_sqlite_url(url: str) -> bool:
    """True when *url* names the embedded SQLite backend."""
    return bool(url) and url.strip().lower().startswith(_SQLITE_SCHEMES)


def sqlite_path_from_url(url: str) -> str:
    """Extract a filesystem path (or ``:memory:``) from a ``sqlite://`` URL.

    Accepts the common spellings:
      * ``sqlite:///abs/path.db``        -> ``/abs/path.db``
      * ``sqlite://./rel/path.db``       -> ``./rel/path.db``
      * ``sqlite:///:memory:``           -> ``:memory:``
      * ``sqlite://:memory:``            -> ``:memory:``
    """
    raw = url.strip()
    for scheme in ("sqlite3://", "sqlite://"):
        if raw.lower().startswith(scheme):
            rest = raw[len(scheme):]
            break
    else:
        rest = raw
    # Strip any query string (e.g. ?mode=memory) — we handle pragmas ourselves.
    rest = rest.split("?", 1)[0]
    if rest in (":memory:", "/:memory:", "//:memory:"):
        return ":memory:"
    # sqlite:///abs -> rest == "/abs"; sqlite://rel -> rest == "rel"
    if rest.startswith("/"):
        return rest
    return rest


# A pure-SQLite expression that yields a RFC-4122 v4 UUID string.  Used both as a
# column DEFAULT in the generated SQLite DDL and as the runtime replacement for
# ``gen_random_uuid()`` in translated queries (rare — most inserts rely on the
# column default).
SQLITE_UUID4_EXPR = (
    "(lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || "
    "substr(lower(hex(randomblob(2))),2) || '-' || "
    "substr('89ab',abs(random())%4+1,1) || "
    "substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))))"
)

# ── regexes (compiled once) ────────────────────────────────────────────────────

_RE_JSONB_CAST_EXTRACT = re.compile(
    r"([\w.]+)\s*::\s*jsonb\s*->>\s*'([^']+)'", re.IGNORECASE)
_RE_JSON_EXTRACT = re.compile(r"([\w.]+)\s*->>\s*'([^']+)'")
_RE_ANY = re.compile(
    r"(\$\d+|\?)\s*=\s*ANY\s*\(\s*([\w.]+)\s*\)", re.IGNORECASE)
_RE_CAST = re.compile(r"::\s*[A-Za-z_][A-Za-z0-9_]*(\s*\[\s*\])?")
_RE_GEN_UUID = re.compile(r"gen_random_uuid\s*\(\s*\)", re.IGNORECASE)
_RE_NOW = re.compile(r"\bnow\s*\(\s*\)", re.IGNORECASE)
_RE_CURRENT_TS = re.compile(r"\bcurrent_timestamp\b", re.IGNORECASE)
_RE_FOR_UPDATE_SKIP = re.compile(
    r"\bFOR\s+UPDATE\s+SKIP\s+LOCKED\b", re.IGNORECASE)
_RE_FOR_UPDATE = re.compile(r"\bFOR\s+UPDATE\b", re.IGNORECASE)
_RE_SKIP_LOCKED = re.compile(r"\bSKIP\s+LOCKED\b", re.IGNORECASE)
_RE_ILIKE = re.compile(r"\bILIKE\b", re.IGNORECASE)
_RE_PARAM = re.compile(r"\$(\d+)")


def translate_sql(sql: str) -> str:
    """Translate a Postgres query string to its SQLite equivalent.

    Placeholder ``$N`` -> ``?`` re-binding is NOT done here; use
    :func:`translate_query` for the combined SQL + parameter transform.
    """
    sql = _RE_JSONB_CAST_EXTRACT.sub(r"json_extract(\1, '$.\2')", sql)
    sql = _RE_JSON_EXTRACT.sub(r"json_extract(\1, '$.\2')", sql)
    sql = _RE_ANY.sub(
        r"EXISTS (SELECT 1 FROM json_each(\2) WHERE value = \1)", sql)
    sql = _RE_GEN_UUID.sub(SQLITE_UUID4_EXPR, sql)
    # Remaining ::type casts (::jsonb, ::uuid, ::text[], ...) become no-ops.
    sql = _RE_CAST.sub("", sql)
    sql = _RE_NOW.sub("CURRENT_TIMESTAMP", sql)
    sql = _RE_CURRENT_TS.sub("CURRENT_TIMESTAMP", sql)
    sql = _RE_FOR_UPDATE_SKIP.sub("", sql)
    sql = _RE_FOR_UPDATE.sub("", sql)
    sql = _RE_SKIP_LOCKED.sub("", sql)
    sql = _RE_ILIKE.sub("LIKE", sql)
    return sql


def _rebind_params(sql: str, args: Sequence[Any]) -> tuple[str, list[Any]]:
    """Rewrite ``$N`` placeholders to ``?`` and reorder *args* to match.

    Postgres allows a placeholder to appear out of order or more than once
    (``... WHERE a = $1 OR b = $1``).  SQLite ``?`` binds positionally in
    order of appearance, so we walk the placeholders left-to-right and build a
    fresh parameter list, duplicating values where a ``$N`` repeats.
    """
    out_params: list[Any] = []

    def _sub(m: "re.Match[str]") -> str:
        idx = int(m.group(1)) - 1
        if idx < 0 or idx >= len(args):
            raise IndexError(
                f"placeholder ${idx + 1} out of range for {len(args)} args")
        out_params.append(adapt_param(args[idx]))
        return "?"

    new_sql = _RE_PARAM.sub(_sub, sql)
    return new_sql, out_params


def translate_query(sql: str, args: Sequence[Any]) -> tuple[str, list[Any]]:
    """Full transform: translate dialect *and* rebind ``$N`` -> ``?``."""
    translated = translate_sql(sql)
    return _rebind_params(translated, args)


# ── parameter / value adaptation ───────────────────────────────────────────────

def adapt_param(value: Any) -> Any:
    """Convert a Python value from the asyncpg calling convention to one the
    stdlib ``sqlite3`` driver accepts and that round-trips through our TEXT/BLOB
    column mapping.

      * ``uuid.UUID``            -> ``str``
      * ``list`` / ``tuple`` / ``dict`` (arrays, jsonb) -> JSON ``str``
      * ``datetime`` / ``date``  -> ``'YYYY-MM-DD HH:MM:SS[.ffffff]'`` (UTC),
                                    matching SQLite ``CURRENT_TIMESTAMP`` ordering
      * ``bool``                 -> left as-is (sqlite3 stores as 0/1)
      * ``bytes`` / ``memoryview`` -> ``bytes`` (BLOB)
      * everything else          -> unchanged
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return json.dumps([_json_default(v) for v in value])
    if isinstance(value, dict):
        return json.dumps(value, default=_json_default)
    if isinstance(value, _dt.datetime):
        dt = value
        if dt.tzinfo is not None:
            dt = dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, memoryview):
        return bytes(value)
    return value


# Postgres native ARRAY (``type[]``) columns.  asyncpg returns these as Python
# lists; SQLite stores them as JSON text, so the backend adapter parses these
# specific result columns back into lists on read.  (jsonb columns are NOT in
# this set: asyncpg returns *those* as JSON strings too, so leaving them as text
# keeps both backends identical — the query layer json.loads() them itself.)
ARRAY_COLUMNS = frozenset({"tags", "tooth_ids", "received_chunks"})


def parse_array_column(name: str, value: Any) -> Any:
    """Parse a known ARRAY result column's JSON text into a Python list."""
    if name not in ARRAY_COLUMNS or value is None or isinstance(value, (list, tuple)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, TypeError):
            pass
    return value


def _json_default(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v
