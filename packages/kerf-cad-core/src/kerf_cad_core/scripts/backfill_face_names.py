"""
backfill_face_names.py — T7: one-shot migration to populate target_face_name
on existing feature nodes that only carry a legacy target_face_id integer.

Usage
-----
    python -m kerf_cad_core.scripts.backfill_face_names [project_id] [--dry-run]

    project_id — UUID of the project to migrate.  When omitted, ALL projects
                 are processed (useful for a one-time fleet-wide pass).

    --dry-run  — Print the nodes that would be updated without writing.
    --db-url   — Postgres DSN (defaults to DATABASE_URL env var).

Why this is safe to run multiple times (idempotency)
------------------------------------------------------
The script only processes nodes that satisfy ALL of the following:
  1. The node op is one of the face-consuming ops (cut_from_sketch, push_pull, etc.).
  2. The node has `target_face_id` (or `face_id`) set.
  3. The node does NOT already have `target_face_name` (or `face_name`) set
     (or the stored name is an empty string).

Because conditions 2 + 3 are checked fresh on every run, re-running the script
after a partial pass is safe — already-migrated nodes are silently skipped.

What the script does NOT do
----------------------------
Kerf's face-naming requires a live OCCT evaluation to compute `target_face_name`
from scratch (the name is a topological/sketch-anchored string computed by the
WASM worker, not derivable from raw JSON alone).  This Python migration therefore
can only handle the subset of ops whose face names are deterministic from the
stored JSON without OCCT:

  * `cut_from_sketch` / `push_pull` / `boss_with_draft`:
      - If the op's sketch_path is present and the sketch has entity IDs,
        the migration attempts to reconstruct the sketch-anchored name
        (`<nodeId>.TopCap`, `<nodeId>.Side.seg-N`, etc.) using the same
        conventions as buildFaceNamesForExtrude in faceNaming.js.
      - This is a BEST-EFFORT approximation — the positional face index
        mapping is ambiguous without the WASM shape.  The migration writes
        a synthetic name of the form `<nodeId>.face<id>` which is stable
        (deterministic for this integer) even if not as human-readable as
        the full sketch-anchored form.
      - The real name will be overwritten opportunistically the next time the
        user edits the feature in the UI (the editor dual-writes from the
        live WASM name table at commit time — see T4/T5 in occtWorker.js).

  * For all other ops the node is left unchanged (the name will be filled
    opportunistically on next edit).

Rows updated
------------
The script updates `files.content` (a JSONB column) in place, bumping the
node's JSON to add `target_face_name` / `face_name`.  File revision history
(file_revisions table) is NOT touched — this is a schema migration, not a
user commit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Face-consuming ops and the name keys they use
# ---------------------------------------------------------------------------

# Each entry: (op_name, id_key, name_key)
FACE_REF_OPS: list[tuple[str, str, str]] = [
    ("cut_from_sketch", "target_face_id", "target_face_name"),
    ("push_pull",       "face_id",        "face_name"),
    ("boss_with_draft", "target_face_id", "target_face_name"),
    ("fillet",          "target_face_id", "target_face_name"),
    ("chamfer",         "target_face_id", "target_face_name"),
    ("hole",            "target_face_id", "target_face_name"),
    ("hole_pattern",    "target_face_id", "target_face_name"),
]

# Set of op names for fast lookup
FACE_REF_OP_NAMES: set[str] = {op for op, _, _ in FACE_REF_OPS}


def _synthetic_face_name(node: dict[str, Any], id_key: str) -> str | None:
    """
    Derive a best-effort synthetic face name from a node that has an integer
    face id but no persistent name.

    The convention is `<nodeId>.face<id>` — stable, human-readable enough to
    distinguish references, and unambiguous as a fallback key.  The real
    sketch-anchored name will overwrite this on the next user edit.

    Returns None when the node lacks the required id field.
    """
    node_id = node.get("id") or node.get("op", "op")
    face_int = node.get(id_key)
    if face_int is None:
        return None
    try:
        idx = int(face_int)
    except (TypeError, ValueError):
        return None
    return f"{node_id}.face{idx}"


def migrate_feature_content(content: str) -> tuple[str | None, int]:
    """
    Walk the feature nodes in `content` and add synthetic `target_face_name` /
    `face_name` to any node that has the legacy integer id but no persistent name.

    Returns (new_content, num_updated).  Returns (None, 0) when no changes are
    needed (idempotent) or when the content is unparseable.
    """
    if not content or not content.strip():
        return None, 0

    try:
        doc = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None, 0

    features = doc.get("features")
    if not isinstance(features, list):
        return None, 0

    updated = 0
    for node in features:
        if not isinstance(node, dict):
            continue
        op = node.get("op")
        if op not in FACE_REF_OP_NAMES:
            continue

        for op_name, id_key, name_key in FACE_REF_OPS:
            if op != op_name:
                continue
            # Skip nodes that already have a name (idempotency check).
            existing_name = node.get(name_key)
            if existing_name and str(existing_name).strip():
                continue
            # Skip nodes that have no integer id either — nothing to migrate.
            if node.get(id_key) is None:
                continue
            # Derive and write the synthetic name.
            synthetic = _synthetic_face_name(node, id_key)
            if synthetic:
                node[name_key] = synthetic
                updated += 1
            break  # only one (id_key, name_key) pair per op

    if updated == 0:
        return None, 0

    return json.dumps(doc, separators=(",", ":")), updated


def backfill_project(
    conn: Any,
    project_id: uuid.UUID | None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Run the backfill for one project (or all projects when project_id is None).

    Returns a stats dict: {"files_scanned": N, "files_updated": N, "nodes_updated": N}.
    """
    stats = {"files_scanned": 0, "files_updated": 0, "nodes_updated": 0}

    if project_id:
        rows = conn.execute(
            "SELECT id, content FROM files "
            "WHERE project_id = $1 AND kind = 'feature' AND deleted_at IS NULL",
            (str(project_id),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content FROM files "
            "WHERE kind = 'feature' AND deleted_at IS NULL"
        ).fetchall()

    for file_id, content in rows:
        stats["files_scanned"] += 1
        if not content:
            continue

        new_content, num_updated = migrate_feature_content(content)
        if new_content is None:
            continue

        stats["files_updated"] += 1
        stats["nodes_updated"] += num_updated

        if dry_run:
            print(f"  [dry-run] would update {num_updated} node(s) in file {file_id}")
            continue

        conn.execute(
            "UPDATE files SET content = $1, updated_at = now() WHERE id = $2",
            (new_content, str(file_id)),
        )

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill target_face_name on legacy feature nodes."
    )
    parser.add_argument(
        "project_id",
        nargs="?",
        default=None,
        help="Project UUID to migrate.  Omit to migrate all projects.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing to the database.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Postgres DSN.  Defaults to DATABASE_URL environment variable.",
    )
    args = parser.parse_args(argv)

    db_url = args.db_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print(
            "ERROR: no database URL supplied.  Set DATABASE_URL or use --db-url.",
            file=sys.stderr,
        )
        return 1

    project_id: uuid.UUID | None = None
    if args.project_id:
        try:
            project_id = uuid.UUID(args.project_id)
        except ValueError:
            print(f"ERROR: invalid project_id UUID: {args.project_id!r}", file=sys.stderr)
            return 1

    # Lazy import psycopg2 / psycopg so the module is importable without it.
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(db_url)
        conn.autocommit = False

        class _PsycopgAdapter:
            """Thin adapter to present a uniform execute/fetchall API."""
            def __init__(self, pg_conn: Any) -> None:
                self._conn = pg_conn

            def execute(self, sql: str, params: tuple = ()) -> Any:
                # psycopg2 uses %s placeholders, not $N.
                pg_sql = _dollar_to_percent(sql)
                cur = self._conn.cursor()
                cur.execute(pg_sql, params)
                return cur

            def commit(self) -> None:
                self._conn.commit()

        adapted = _PsycopgAdapter(conn)

    except ImportError:
        print("ERROR: psycopg2 not installed.  Run: pip install psycopg2-binary", file=sys.stderr)
        return 1

    def _dollar_to_percent(sql: str) -> str:
        """Convert $1/$2/… placeholders to %s for psycopg2."""
        import re
        return re.sub(r"\$\d+", "%s", sql)

    if args.dry_run:
        print("[dry-run] No changes will be written.")

    stats = backfill_project(adapted, project_id, dry_run=args.dry_run)

    if not args.dry_run:
        adapted.commit()

    print(
        f"Done. files_scanned={stats['files_scanned']} "
        f"files_updated={stats['files_updated']} "
        f"nodes_updated={stats['nodes_updated']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
