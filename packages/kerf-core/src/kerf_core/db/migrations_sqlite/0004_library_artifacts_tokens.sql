-- AUTO-GENERATED from ../migrations/0004_library_artifacts_tokens.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

-- 0004_library_artifacts_tokens.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 020_library_submissions.sql ════════════

-- Library Phase 3 — manufacturer-PR submission queue.

create table if not exists library_part_submissions (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    submitter_user_id text not null references users(id) on delete cascade,
    target_workspace_id text not null references workspaces(id) on delete cascade,
    payload text not null,
    status text not null default 'pending'
        check (status in ('pending', 'approved', 'rejected')),
    review_note text not null default '',
    reviewer_id text references users(id) on delete set null,
    created_at text not null default CURRENT_TIMESTAMP,
    updated_at text not null default CURRENT_TIMESTAMP
);

create index if not exists library_part_submissions_status_idx
    on library_part_submissions(status);
create index if not exists library_part_submissions_submitter_idx
    on library_part_submissions(submitter_user_id);
create index if not exists library_part_submissions_target_idx
    on library_part_submissions(target_workspace_id);

-- ════════════ folded: 022_step_tessellation_jobs.sql ════════════

-- Performance Phase 3: server-side STEP pre-tessellation.

create table if not exists step_tessellation_jobs (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    file_id text not null references files(id) on delete cascade,
    status text not null default 'queued'
        check (status in ('queued','running','done','error')),
    error text,
    mesh_storage_key text,
    started_at text,
    finished_at text,
    -- folded from 047_step_tess_input_spec.sql (0007)
    input_spec text,
    content_sha256 text,
    created_at text not null default CURRENT_TIMESTAMP
);

create index if not exists step_tessellation_jobs_status_idx
    on step_tessellation_jobs(status, created_at)
    where status in ('queued','running');

create unique index if not exists step_tessellation_jobs_file_id_unique
    on step_tessellation_jobs(file_id);

-- files.mesh_storage_key folded into CREATE TABLE files in 0001_core_identity.sql.

-- ════════════ folded: 024_derived_artifacts.sql ════════════

-- Cross-project derived-artifact cache.
-- derived_kind check updated to include 'step_mesh' (folded from
-- 047_step_tess_input_spec.sql in 0007_step_tess_revision_finalize.sql).

create table if not exists derived_artifacts (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    source_file_id text not null references files(id) on delete cascade,
    content_sha256 text not null,
    derived_kind text not null
        check (derived_kind in ('jscad_mesh', 'sketch_geom2', 'circuit_board_3d', 'step_mesh')),
    payload blob not null,
    payload_size_bytes int not null default 0,
    created_at text not null default CURRENT_TIMESTAMP,
    last_accessed_at text not null default CURRENT_TIMESTAMP
);

create unique index if not exists derived_artifacts_key_idx
    on derived_artifacts(source_file_id, content_sha256, derived_kind);
create index if not exists derived_artifacts_lru_idx
    on derived_artifacts(last_accessed_at);

-- ════════════ folded: 025_api_tokens.sql ════════════

-- API tokens for kerf-sdk auth (workspace-scoped).

create table if not exists api_tokens (
    id          text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    workspace_id text not null references workspaces(id) on delete cascade,
    user_id     text not null references users(id) on delete cascade,
    token_hash  text unique not null,
    name        text not null,
    scopes      text not null default '["workspace:member-role"]',
    last_used_at text,
    revoked_at  text,
    -- folded from 051_billing_buckets.sql (0008): per-token daily spend cap
    max_spend_per_day_usd numeric(10, 2) not null default 50.00,
    spend_today_usd       numeric(10, 4) not null default 0.00,
    spend_today_date      date           not null default current_date,
    created_at  text not null default CURRENT_TIMESTAMP
);
create index if not exists api_tokens_workspace_idx on api_tokens(workspace_id);
create index if not exists api_tokens_user_idx on api_tokens(user_id);
create index if not exists api_tokens_token_hash_idx on api_tokens(token_hash);
