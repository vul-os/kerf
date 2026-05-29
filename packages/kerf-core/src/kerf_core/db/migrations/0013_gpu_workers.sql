-- 0013_gpu_workers.sql
-- GPU worker enrollment + BYO dispatch tables.
--
-- gpu_workers: one row per enrolled worker machine.  Users enroll their
--   own GPU machine by calling POST /api/workers/enroll; the API mints a
--   token (stored as a bcrypt hash) returned ONCE in plaintext.  The worker
--   daemon uses this token to authenticate heartbeat + claim-job calls.
--
-- gpu_worker_jobs: join table linking a worker to the render jobs it ran.
--   Used for COGS attribution and per-worker utilisation reporting.
--
-- render_jobs: two new columns are added inline — preferred_worker_id (so a
--   SelfHostedWorkerBackend-submitted job is only claimable by that worker)
--   and billing_bucket (so charge_render can short-circuit on 'byo').
--
-- All DDL is CREATE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS — fully idempotent.

CREATE TABLE IF NOT EXISTS gpu_workers (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            text        NOT NULL,
    token_hash      text        NOT NULL DEFAULT '',
    capabilities    jsonb       NOT NULL DEFAULT '{}',
    status          text        NOT NULL DEFAULT 'offline'
                    CHECK (status IN ('online', 'offline', 'busy', 'revoked')),
    last_seen_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS gpu_workers_user_id_idx ON gpu_workers (user_id);
CREATE INDEX IF NOT EXISTS gpu_workers_status_idx  ON gpu_workers (status);

CREATE TABLE IF NOT EXISTS gpu_worker_jobs (
    worker_id       uuid        NOT NULL REFERENCES gpu_workers(id) ON DELETE CASCADE,
    render_job_id   uuid        NOT NULL REFERENCES render_jobs(id) ON DELETE CASCADE,
    picked_up_at    timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz,
    PRIMARY KEY (worker_id, render_job_id)
);

CREATE INDEX IF NOT EXISTS gpu_worker_jobs_worker_id_idx
    ON gpu_worker_jobs (worker_id);
CREATE INDEX IF NOT EXISTS gpu_worker_jobs_render_job_id_idx
    ON gpu_worker_jobs (render_job_id);

-- render_jobs.preferred_worker_id + billing_bucket are defined in
-- 0010_github_app_render.sql (folded into the render_jobs baseline per the
-- clean-baseline directive — no ALTER shims).
CREATE INDEX IF NOT EXISTS render_jobs_preferred_worker_idx
    ON render_jobs (preferred_worker_id)
    WHERE preferred_worker_id IS NOT NULL;
