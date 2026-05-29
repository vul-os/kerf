-- 0010_github_app_render.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 063_github_installation.sql ════════════
-- github_installation_id folded into CREATE TABLE cloud_github_tokens
-- in 0006_github_workshop.sql.

-- ════════════ folded: 064_cloud_github_tokens_repair.sql ════════════
-- Repair migration for legacy DBs that had a partial cloud_github_tokens.
-- Since DBs are always reset on deploy, the full table is created by
-- 0006_github_workshop.sql; this repair and its backfill ALTERs are obsolete.

-- ════════════ folded: 065_render_jobs.sql ════════════

-- Render job queue for the Blender Cycles worker (T-106b).
--
-- Self-contained and fully idempotent: CREATE IF NOT EXISTS throughout.
-- Safe to run on fresh databases and on already-migrated ones alike.

CREATE TABLE IF NOT EXISTS render_jobs (
    id              uuid PRIMARY KEY,
    user_id         uuid,
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
    -- billing_bucket: 'kerf_paid' (hosted vendor) | 'byo' (self-hosted worker).
    preferred_worker_id uuid,
    billing_bucket      text        NOT NULL DEFAULT 'kerf_paid',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
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
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS render_free_quota (
    user_id                 uuid    NOT NULL,
    month                   text    NOT NULL,  -- 'YYYY-MM'
    hero_renders_remaining  int     NOT NULL DEFAULT 3,
    PRIMARY KEY (user_id, month)
);

CREATE TABLE IF NOT EXISTS render_usage_events (
    job_id          uuid        PRIMARY KEY,
    user_id         uuid,
    preset          text        NOT NULL DEFAULT '',
    gpu_seconds     float8      NOT NULL DEFAULT 0,
    credits_charged float8      NOT NULL DEFAULT 0,
    recorded_at     timestamptz NOT NULL DEFAULT now()
);
