-- AUTO-GENERATED from ../migrations/0009_workshop_gallery.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

-- 0009_workshop_gallery.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- Workshop media is now files-in-repo (GitHub-style): images live as
-- files under a project `workshop/` folder and the cover is a repo
-- cover.* file (with the auto-generated thumbnail as the default).
-- The old DB-backed `project_workshop_images` gallery was retired —
-- since DBs are reset, the table is simply dropped from this baseline
-- rather than left as dead schema.

-- ════════════ folded: 061_user_github_id.sql ════════════
-- github_id folded into CREATE TABLE users in 0001_core_identity.sql.
-- users_github_id_unique index created inline with CREATE TABLE in 0001.

-- ════════════ folded: 062_workshop_readme.sql ════════════
-- readme, readme_generated_at, cover_storage_key, cover_generated_at folded
-- into CREATE TABLE projects in 0001_core_identity.sql.
