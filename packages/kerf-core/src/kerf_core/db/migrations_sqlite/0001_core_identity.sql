-- AUTO-GENERATED from ../migrations/0001_core_identity.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

-- 0001_core_identity.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.
-- Re-ordered 2026-05-19: workspaces moved before projects so the FK
-- workspace_id → workspaces(id) can be declared inline in CREATE TABLE.

-- ════════════ folded: 001_init.sql ════════════

-- Kerf initial schema.
-- Generated for backend bootstrap.


create table if not exists users (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    email text collate nocase unique not null,
    password_hash text,
    google_id text unique,
    name text not null default '',
    avatar_url text not null default '',
    account_role text not null default 'user' check (account_role in ('user','admin','system')),
    is_system boolean not null default false,
    email_verified boolean not null default false,
    -- folded from 009_library_v15.sql (0002)
    is_verified_publisher boolean not null default false,
    -- folded from 016_user_avatar_storage.sql (0003)
    avatar_storage_key text,
    avatar_updated_at text,
    -- folded from 017_user_preferences.sql (0003)
    preferences text not null default '{}',
    -- folded from 061_user_github_id.sql (0009)
    github_id text,
    created_at text not null default CURRENT_TIMESTAMP
);
create index if not exists users_account_role_idx on users(account_role);
create index if not exists users_is_verified_publisher_idx on users(is_verified_publisher) where is_verified_publisher = true;
create unique index if not exists users_github_id_unique on users (github_id) where github_id is not null;

create table if not exists refresh_tokens (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    user_id text not null references users(id) on delete cascade,
    token_hash text unique not null,
    expires_at text not null,
    revoked_at text,
    created_at text not null default CURRENT_TIMESTAMP
);
create index if not exists refresh_tokens_user_id_idx on refresh_tokens(user_id);

-- Single-use, expiring tokens for email verification and password
-- reset. token_hash stores sha256(token); the raw token only ever
-- lives in the emailed link. used_at marks consumption (single use).
create table if not exists email_tokens (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    user_id text not null references users(id) on delete cascade,
    kind text not null check (kind in ('verify','reset')),
    token_hash text unique not null,
    expires_at text not null,
    used_at text,
    created_at text not null default CURRENT_TIMESTAMP
);
create index if not exists email_tokens_user_id_idx on email_tokens(user_id);
create index if not exists email_tokens_token_hash_idx on email_tokens(token_hash);

-- ════════════ folded: 003_workspaces.sql ════════════
-- (moved before projects so the FK can be declared inline)

-- Workspaces (orgs) — multi-member containers above projects.

create table if not exists workspaces (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    slug text not null unique,
    name text not null,
    avatar_storage_key text,
    created_by text not null references users(id),
    created_at text not null default CURRENT_TIMESTAMP,
    updated_at text not null default CURRENT_TIMESTAMP
);
create index if not exists workspaces_slug_idx on workspaces(slug);

create table if not exists workspace_members (
    workspace_id text not null references workspaces(id) on delete cascade,
    user_id text not null references users(id) on delete cascade,
    role text not null check (role in ('owner','admin','member')),
    created_at text not null default CURRENT_TIMESTAMP,
    primary key (workspace_id, user_id)
);
create index if not exists workspace_members_user_idx on workspace_members(user_id);

create table if not exists workspace_invites (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    workspace_id text not null references workspaces(id) on delete cascade,
    email text collate nocase not null,
    role text not null check (role in ('owner','admin','member')),
    token text unique not null,
    created_by text not null references users(id) on delete cascade,
    created_at text not null default CURRENT_TIMESTAMP
);
create index if not exists workspace_invites_workspace_idx on workspace_invites(workspace_id);
create index if not exists workspace_invites_email_idx on workspace_invites(email);

-- projects now references workspaces inline (workspace_id FK was previously
-- added via ALTER TABLE in the folded 003_workspaces section; project_type
-- column was added in 0002 and dropped in 0003 — omitted from final shape).
create table if not exists projects (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    workspace_id text not null references workspaces(id) on delete cascade,
    name text not null,
    description text not null default '',
    visibility text not null default 'private' check (visibility in ('private','unlisted','public')),
    -- Workshop fork lineage: which public project this was forked from
    -- (null = original). on delete set null so deleting the source
    -- never cascade-deletes its forks.
    forked_from_project_id text references projects(id) on delete set null,
    -- Who created this project. Activity feed joins through this to render
    -- "<user> created the project" rows. on delete set null preserves the
    -- project's history if the user is later deleted (becomes anon).
    created_by text references users(id) on delete set null,
    -- folded from 006_project_thumbnails.sql (0002)
    thumbnail_storage_key text,
    thumbnail_updated_at text,
    -- folded from 015_project_tags.sql (0003): project_type dropped, tags added
    tags text not null default '[]',
    -- folded from 062_workshop_readme.sql (0009)
    readme text,
    readme_generated_at text,
    cover_storage_key text,
    cover_generated_at text,
    created_at text not null default CURRENT_TIMESTAMP,
    updated_at text not null default CURRENT_TIMESTAMP
);
create index if not exists projects_workspace_id_idx on projects(workspace_id);
create index if not exists projects_forked_from_idx on projects(forked_from_project_id);
create index if not exists projects_created_by_idx on projects(created_by);

create table if not exists share_links (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    project_id text not null references projects(id) on delete cascade,
    token text unique not null,
    role text not null check (role in ('editor','viewer')),
    expires_at text,
    revoked_at text,
    max_uses int,
    uses int not null default 0,
    created_by text not null references users(id) on delete cascade,
    created_at text not null default CURRENT_TIMESTAMP
);
create index if not exists share_links_project_id_idx on share_links(project_id);

create table if not exists files (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    project_id text not null references projects(id) on delete cascade,
    parent_id text references files(id) on delete cascade,
    name text not null,
    -- final kind enumeration folded from 29 incremental kind migrations
    -- (010,011,012,019,021,023,026,033-046,053,054,056-061_kind_wiring)
    kind text not null default 'file' constraint files_kind_check check (kind in ('file','text','folder','assembly','step','drawing','sketch','part','feature','circuit','equations','material','simulation','script','step-ref','assembly_lock','canvas','schedule','view','sheet','duct','pipe','conduit','subd','mesh','render','section','cam_layered','tool','plc_st','plc_ld','quadmesh','print','gem','wiring','firmware','mold','pid','optics','layup','dental','hdl_vhdl','hdl_verilog','spice_netlist','gds_layout','oasis_layout','lef_lib','def_design','liberty_lib','silicon_flow','silicon_pdk','firmware_project','eco','sysml','system','harness')),
    content text not null default '',
    storage_key text,
    mime_type text,
    size bigint,
    version bigint not null default 1,
    deleted_at text,
    -- folded from 022_step_tessellation_jobs.sql (0004)
    mesh_storage_key text,
    -- folded from 029_script_extension.sql (0005)
    extension text,
    -- Activity feed attribution: who created the file. Without this, the
    -- 'file_created' / 'file_deleted' activity events rendered as
    -- "Someone created main.jscad" because the SQL had to hardcode
    -- user_id := NULL. on delete set null preserves history if the
    -- user is later deleted (becomes anon).
    created_by text references users(id) on delete set null,
    created_at text not null default CURRENT_TIMESTAMP,
    updated_at text not null default CURRENT_TIMESTAMP
);
create index if not exists files_project_id_idx on files(project_id);
create index if not exists files_parent_id_idx on files(parent_id);
create index if not exists files_storage_key_idx on files(storage_key);
create index if not exists files_deleted_at_idx on files(deleted_at);
create index if not exists files_extension_idx on files(extension);
create index if not exists files_created_by_idx on files(created_by);
create index if not exists files_kind_idx on files(kind);

create table if not exists file_revisions (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    file_id text not null references files(id) on delete cascade,
    content text not null,
    source text not null check (source in ('user','llm','tool','restore')),
    user_id text references users(id) on delete set null,
    -- folded from 013_revision_diffs.sql (0003): diff-based + compressed revisions
    -- final check folded from 049_revision_content_ref.sql (0007): 'ref' added
    kind text not null default 'base'
        check (kind in ('base', 'diff', 'ref')),
    content_gz blob,
    parent_revision_id text
        references file_revisions(id) on delete set null,
    content_preview text,
    -- folded from 018_revision_sha256.sql (0003): chain-corruption detection
    content_sha256 blob,
    -- folded from 048_revision_compaction.sql (0007): codec signal
    content_codec text not null default 'plain'
        check (content_codec in ('plain', 'gzip')),
    created_at text not null default CURRENT_TIMESTAMP
);
create index if not exists file_revisions_file_id_created_at_idx on file_revisions(file_id, created_at desc);
create index if not exists file_revisions_file_id_kind_idx
    on file_revisions(file_id, kind);
create index if not exists file_revisions_file_sha256_idx
    on file_revisions(file_id, content_sha256)
    where content_sha256 is not null;
create index if not exists file_revisions_parent_revision_id_idx
    on file_revisions(parent_revision_id)
    where parent_revision_id is not null;
create index if not exists file_revisions_sha256_base_idx
    on file_revisions(content_sha256)
    where kind = 'base';

-- chat_threads.created_by: who created the thread. Activity feed joins
-- through this to render "<user> asked …" rows; without it every chat
-- event renders as "Unknown asked …". on delete set null so a deleted
-- user's old threads survive as anonymised history.
create table if not exists chat_threads (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    project_id text not null references projects(id) on delete cascade,
    file_id text references files(id) on delete set null,
    title text not null default '',
    is_starred boolean not null default false,
    last_message_at text,
    model text,
    created_by text references users(id) on delete set null,
    created_at text not null default CURRENT_TIMESTAMP,
    updated_at text not null default CURRENT_TIMESTAMP
);
create index if not exists chat_threads_project_id_idx on chat_threads(project_id);
create index if not exists chat_threads_file_id_idx on chat_threads(file_id);
create index if not exists chat_threads_created_by_idx on chat_threads(created_by);

-- chat_messages.user_id: who sent this message. Only meaningful for
-- role='user' rows; assistant/tool rows leave it null. Activity feed
-- joins through this to render "<user> asked …" preview rows.
-- chat_messages.is_error: true when a tool execution failed server-side.
-- The LLM transport layer forwards this flag into the Anthropic
-- tool_result block so the model sees the failure instead of a blank
-- success result.
create table if not exists chat_messages (
    id text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    thread_id text not null references chat_threads(id) on delete cascade,
    role text not null check (role in ('user','assistant','system','tool')),
    content text not null default '',
    part_refs text not null default '[]',
    tool_calls text not null default '[]',
    tool_call_id text,
    model text,
    user_id text references users(id) on delete set null,
    is_error boolean not null default false,
    created_at text not null default CURRENT_TIMESTAMP
);
create index if not exists chat_messages_thread_id_idx on chat_messages(thread_id);
create index if not exists chat_messages_user_id_idx on chat_messages(user_id);

-- ════════════ folded: dental_cases (T-171) ════════════
-- The kerf-dental package needs a per-case anatomy / treatment record
-- attached to a project. Folded into the kerf-core baseline per the
-- clean-baseline rule (no package-local migrations on the shared DB).
create table if not exists dental_cases (
    id          text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    project_id  text not null references projects(id) on delete cascade,
    patient_ref text not null default '',
    tooth_ids   text not null default '[]',
    treatment   text not null default 'crown'
        check (treatment in ('crown', 'aligner', 'guide', 'bridge', 'veneer', 'inlay')),
    notes       text not null default '',
    created_at  text not null default CURRENT_TIMESTAMP,
    updated_at  text not null default CURRENT_TIMESTAMP
);
create index if not exists dental_cases_project_id_idx
    on dental_cases(project_id);
create index if not exists dental_cases_treatment_idx
    on dental_cases(treatment);

-- ════════════ rate_limit_buckets (T-310) ════════════
-- Sliding-window counter keyed on caller (user_id or IP) + endpoint name.
-- Each window_start is a window_seconds-rounded text; INSERT ... ON
-- CONFLICT DO UPDATE increments atomically. Multi-machine safe — state
-- lives in Postgres. See packages/kerf-core/src/kerf_core/rate_limit.py
-- for the helper and packages/kerf-core/tests/test_rate_limit.py for
-- behaviour.
create table if not exists rate_limit_buckets (
    bucket_key   text not null,
    window_start text not null,
    count        integer not null default 0,
    primary key (bucket_key, window_start)
);
create index if not exists rate_limit_buckets_window_idx
    on rate_limit_buckets(window_start);

-- ════════════ billing_scheduler_state (T-402 R3) ════════════
-- Single-row idempotency guard for the StorageBillingWorker.  The worker
-- checks last_storage_debit_month before calling monthly_storage_debit() and
-- only proceeds when the current YYYY-MM differs from the stored value.
-- After a successful sweep, last_storage_debit_month is updated to the
-- current YYYY-MM, making every subsequent tick within that month a no-op.
-- id=1 is the sentinel singleton row; INSERT ... ON CONFLICT DO NOTHING
-- ensures the row exists before the first UPDATE check.
create table if not exists billing_scheduler_state (
    id                        integer primary key default 1 check (id = 1),
    last_storage_debit_month  text not null default ''
);
