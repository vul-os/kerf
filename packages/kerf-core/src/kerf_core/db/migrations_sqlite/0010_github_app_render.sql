-- AUTO-GENERATED from ../migrations/0010_github_app_render.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

-- 0010_github_app_render.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 063_github_installation.sql ════════════
-- github_installation_id originally folded into CREATE TABLE
-- cloud_github_tokens in 0006_github_workshop.sql; that table (and this
-- column with it) was dropped 2026-07-18 — see the tombstone comment in
-- 0006_github_workshop.sql for why.

-- ════════════ folded: 064_cloud_github_tokens_repair.sql ════════════
-- Repair migration for legacy DBs that had a partial cloud_github_tokens.
-- Moot twice over now: DBs are always reset on deploy, and
-- cloud_github_tokens itself was dropped 2026-07-18 (see
-- 0006_github_workshop.sql).

-- ════════════ folded: 065_render_jobs.sql ════════════

-- Render job queue for the Blender Cycles worker (T-106b).
--
-- Self-contained and fully idempotent: CREATE IF NOT EXISTS throughout.
-- Safe to run on fresh databases and on already-migrated ones alike.
--
-- billing_bucket ('kerf_paid' | 'byo') dropped 2026-07-18: Kerf has no
-- billing anywhere (decisions.md 2026-07-17 "no billing anywhere; BYO
-- boxes"). It had become a legacy label nobody read — no query branched
-- on its value, only logged/echoed it (see routes_workers.py history) —
-- so it was removed along with the dead reads/writes rather than kept.

CREATE TABLE IF NOT EXISTS render_jobs (
    id              text PRIMARY KEY,
    user_id         text,
    scene_blob_hash text        NOT NULL DEFAULT '',
    preset          text        NOT NULL DEFAULT 'standard',
    status          text        NOT NULL DEFAULT 'queued',
    samples_done    int         NOT NULL DEFAULT 0,
    samples_total   int         NOT NULL DEFAULT 0,
    signed_url      text,
    result_key      text,
    error           text,
    -- GPU-worker dispatch (Wave 4A GPU-FOUNDATION). preferred_worker_id
    -- points at gpu_workers(id) defined in 0013_gpu_workers.sql; no FK
    -- because the baseline order is render_jobs (0010) before gpu_workers
    -- (0013) — relationship enforced at app level.
    preferred_worker_id text,
    created_at      text NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      text NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS render_jobs_user_id_idx ON render_jobs (user_id);
CREATE INDEX IF NOT EXISTS render_jobs_status_idx  ON render_jobs (status);

-- ════════════ folded: 066_render_billing.sql ════════════

-- Render billing tables for the GPU-render credit meter (T-106d).
--
-- render_cache: cache-key deduplification so repeated identical renders
--   cost zero credits (and zero GPU time).
--
-- render_free_quota: Studio-tier monthly entitlement (3 free Hero renders
--   per calendar month).  One row per (user_id, month).
--
-- render_usage_events: append-only ledger of every render job, whether
--   charged or not.  Used for COGS reconciliation and user billing history.
--
-- All tables are fully idempotent (CREATE IF NOT EXISTS / ON CONFLICT DO NOTHING).

CREATE TABLE IF NOT EXISTS render_cache (
    cache_key   text        PRIMARY KEY,
    created_at  text NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS render_free_quota (
    user_id                 text    NOT NULL,
    month                   text    NOT NULL,  -- 'YYYY-MM'
    hero_renders_remaining  int     NOT NULL DEFAULT 3,
    PRIMARY KEY (user_id, month)
);

CREATE TABLE IF NOT EXISTS render_usage_events (
    job_id          text        PRIMARY KEY,
    user_id         text,
    preset          text        NOT NULL DEFAULT '',
    gpu_seconds     float8      NOT NULL DEFAULT 0,
    credits_charged float8      NOT NULL DEFAULT 0,
    recorded_at     text NOT NULL DEFAULT CURRENT_TIMESTAMP
);
