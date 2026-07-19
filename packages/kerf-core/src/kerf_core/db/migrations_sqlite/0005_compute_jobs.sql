-- AUTO-GENERATED from ../migrations/0005_compute_jobs.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

-- 0005_compute_jobs.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 027_fem_jobs.sql ════════════

-- FEM worker: Gmsh mesh generation + FEniCSx / CalculiX stress analysis.

create table if not exists fem_jobs (
    id            text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    file_id       text not null references files(id) on delete cascade,
    project_id    text not null references projects(id) on delete cascade,
    status        text not null default 'queued'
                  check (status in ('queued','running','done','error')),
    input_spec    text not null default '{}',
    result_json   text,
    error         text,
    started_at    text,
    finished_at   text,
    created_at    text not null default CURRENT_TIMESTAMP
);

create index if not exists fem_jobs_status_idx
    on fem_jobs(status, created_at)
    where status in ('queued','running');

create unique index if not exists fem_jobs_file_id_unique
    on fem_jobs(file_id)
    where status in ('queued','running');

-- ════════════ folded: 028_sim_jobs.sql ════════════

-- SPICE simulation worker: ngspice batch simulation of .cir netlists.

create table if not exists sim_jobs (
    id            text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    file_id       text not null references files(id) on delete cascade,
    project_id    text not null references projects(id) on delete cascade,
    status        text not null default 'queued'
                  check (status in ('queued','running','done','error')),
    input_spec    text not null default '{}',
    result_json   text,
    error         text,
    started_at    text,
    finished_at   text,
    created_at    text not null default CURRENT_TIMESTAMP
);

create index if not exists sim_jobs_status_idx
    on sim_jobs(status, created_at)
    where status in ('queued','running');

create unique index if not exists sim_jobs_file_id_unique
    on sim_jobs(file_id)
    where status in ('queued','running');

-- ════════════ folded: 029_script_extension.sql ════════════
-- files.extension folded into CREATE TABLE files in 0001_core_identity.sql.
-- files_extension_idx created inline with CREATE TABLE in 0001.

-- ════════════ folded: 030_cam_jobs.sql ════════════

-- CAM toolpath generation jobs.

create table if not exists cam_jobs (
    id            text primary key default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random())%4+1,1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    file_id       text not null references files(id) on delete cascade,
    project_id    text not null references projects(id) on delete cascade,
    status        text not null default 'queued'
                  check (status in ('queued','running','done','error')),
    input_spec    text not null default '{}',
    result_json   text,
    output_key    text,
    error         text,
    started_at    text,
    finished_at   text,
    created_at    text not null default CURRENT_TIMESTAMP
);

create index if not exists cam_jobs_status_idx
    on cam_jobs(status, created_at)
    where status in ('queued','running');

create unique index if not exists cam_jobs_file_id_unique
    on cam_jobs(file_id)
    where status in ('queued','running');
