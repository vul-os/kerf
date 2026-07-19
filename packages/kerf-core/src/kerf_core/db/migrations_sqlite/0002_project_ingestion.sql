-- AUTO-GENERATED from ../migrations/0002_project_ingestion.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

-- 0002_project_ingestion.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 004_distributor_credentials.sql ════════════

-- Library Phase 2 — operator-configured distributor API credentials.

create table if not exists distributor_credentials (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    name text not null unique,
    enabled boolean not null default true,
    secret_encrypted blob not null,
    rate_limit_per_minute int not null default 60 check (rate_limit_per_minute > 0),
    last_used_at text,
    created_at text not null default CURRENT_TIMESTAMP,
    updated_at text not null default CURRENT_TIMESTAMP
);

create index if not exists distributor_credentials_enabled_idx
    on distributor_credentials(enabled) where enabled = true;

-- ════════════ folded: 005_project_type.sql ════════════
-- project_type column added here and dropped in 015_project_tags (0003);
-- final projects shape has no project_type — omitted from baseline.

-- ════════════ folded: 006_project_thumbnails.sql ════════════
-- thumbnail_storage_key and thumbnail_updated_at folded into
-- CREATE TABLE projects in 0001_core_identity.sql.

-- ════════════ folded: 007_usage_events.sql ════════════

-- usage_events: per-user log of LLM token use and storage deltas.

create table if not exists usage_events (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    user_id text not null references users(id) on delete cascade,
    project_id text references projects(id) on delete set null,
    kind text not null check (kind in ('token','storage','gpu','egress','operator_token')),
    model text,
    input_tokens int not null default 0,
    output_tokens int not null default 0,
    bytes_delta bigint not null default 0,
    usd_cost numeric(12, 6) not null default 0,
    -- folded from 051_billing_buckets.sql (0008)
    payer text not null default 'kerf_paid',
    created_at text not null default CURRENT_TIMESTAMP
);
create index if not exists usage_events_user_id_idx on usage_events(user_id, created_at desc);
create index if not exists usage_events_project_id_idx on usage_events(project_id, created_at desc);
create index if not exists usage_events_kind_idx on usage_events(kind, created_at desc);

-- ════════════ folded: 008_upload_sessions.sql ════════════

-- Resumable / chunked upload sessions.

create table if not exists upload_sessions (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    project_id text not null references projects(id) on delete cascade,
    user_id text not null references users(id) on delete cascade,
    filename text not null,
    size bigint not null,
    mime text,
    sha256 text not null,
    storage_key text not null,
    chunk_size int not null default 5242880,
    total_chunks int not null,
    received_chunks text not null default '[]',
    bytes_received bigint not null default 0,
    complete boolean not null default false,
    -- S3 multipart state folded here so multi-replica deploys share it via DB.
    -- s3_upload_id: the AWS multipart UploadId returned by CreateMultipartUpload.
    -- s3_parts: JSON array of {"ETag": "...", "PartNumber": N} objects, one per
    --   successfully uploaded part.  NULL for local-storage uploads.
    s3_upload_id text,
    s3_parts text not null default '[]',
    s3_temp_key text,
    created_at text not null default CURRENT_TIMESTAMP,
    expires_at text not null default (datetime('now','+24 hours'))
);
create index if not exists upload_sessions_project_id_expires_idx on upload_sessions(project_id, expires_at);
create index if not exists upload_sessions_sha256_idx on upload_sessions(project_id, sha256);

-- ════════════ folded: 009_library_v15.sql ════════════
-- is_verified_publisher folded into CREATE TABLE users in 0001_core_identity.sql.
