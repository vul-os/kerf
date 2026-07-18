-- 0013_firmware_flash_jobs.sql
-- Clean baseline DDL for BYO-worker firmware flash job queue.
--
-- firmware_flash_jobs: one row per cloud-relay flash request.
--   kind        = 'firmware_flash' (constant; future job types may share table)
--   preferred_worker_id = NULL (any BYO worker with capabilities.firmware_flash=true)
--   artifact_key: R2/S3 storage key for the compiled firmware binary
--   board_target: board family string (e.g. 'esp32', 'avr_uno', 'stm32f4')
--   log_key:      storage key for the flash log uploaded by the worker
--
-- Workers claim a row via SELECT ... FOR UPDATE SKIP LOCKED, update status
-- to 'running', perform the flash, then write status='done'/'error' + log_key.
--
-- billing_bucket dropped 2026-07-18: Kerf has no billing anywhere and every
-- flash job already runs on the caller's own hardware (there was never a
-- second value) — no query branched on it, only wrote the constant 'byo'.
-- The LLM tool's JSON response still echoes "billing_bucket": "byo" as a
-- descriptive label (same convention as kerf_render.gpu_backend), it just
-- no longer round-trips through a DB column.
--
-- This is a NEW table (not an extension of render_jobs) to keep worker
-- routing concerns self-contained.

CREATE TABLE IF NOT EXISTS firmware_flash_jobs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid,
    user_id             uuid,
    artifact_key        text        NOT NULL DEFAULT '',
    board_target        text        NOT NULL DEFAULT '',
    kind                text        NOT NULL DEFAULT 'firmware_flash',
    preferred_worker_id uuid,
    status              text        NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','running','done','error','cancelled')),
    log_key             text,
    error               text,
    started_at          timestamptz,
    finished_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS firmware_flash_jobs_status_idx
    ON firmware_flash_jobs (status, created_at)
    WHERE status IN ('queued','running');

CREATE INDEX IF NOT EXISTS firmware_flash_jobs_user_id_idx
    ON firmware_flash_jobs (user_id);
