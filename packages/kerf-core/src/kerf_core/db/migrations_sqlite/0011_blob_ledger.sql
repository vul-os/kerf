-- AUTO-GENERATED from ../migrations/0011_blob_ledger.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

-- 0011_blob_ledger.sql
-- Clean baseline DDL for the oid ref-count ledger (T-134).
--
-- blob_objects: one row per unique content-addressed blob (oid = hex SHA256 or
--   similar digest).  first_workspace_id records which workspace first uploaded
--   this oid (dedup billing: first uploader bears the size; forks pay 0).
--
-- blob_refs: one row per (oid, project, path) tuple that references a blob.
--   Dropping the last ref signals GC eligibility (T-136).  The primary key
--   (oid, project_id, path) ensures add_ref is idempotent via ON CONFLICT.
--
-- last_unref_at: text the oid's ref-count fell to zero (the last
--   blob_refs row was removed); the start of the T-136 GC 72-hour grace
--   window.  NULL = still referenced, or never transitioned to zero.
--   Folded into this baseline CREATE TABLE — the separate
--   0012_blob_gc_last_unref_at ALTER-ADD-COLUMN shim was dropped per the
--   clean-baseline rule.

CREATE TABLE IF NOT EXISTS blob_objects (
    oid                 text        PRIMARY KEY,
    size_bytes          bigint      NOT NULL,
    first_workspace_id  text        REFERENCES workspaces(id) ON DELETE SET NULL,
    last_unref_at       text,
    created_at          text NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS blob_objects_first_workspace_id_idx
    ON blob_objects (first_workspace_id);

CREATE INDEX IF NOT EXISTS blob_objects_last_unref_at_idx
    ON blob_objects (last_unref_at)
    WHERE last_unref_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS blob_refs (
    oid         text        NOT NULL REFERENCES blob_objects(oid) ON DELETE CASCADE,
    project_id  text        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path        text        NOT NULL,
    created_at  text NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (oid, project_id, path)
);

CREATE INDEX IF NOT EXISTS blob_refs_project_id_idx ON blob_refs (project_id);
CREATE INDEX IF NOT EXISTS blob_refs_oid_idx        ON blob_refs (oid);
