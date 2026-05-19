-- 0003_revisions_prefs.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 013_revision_diffs.sql ════════════
-- kind, content_gz, parent_revision_id, content_preview folded into
-- CREATE TABLE file_revisions in 0001_core_identity.sql.

-- ════════════ folded: 014_drop_jewelry_type.sql ════════════
-- project_type constraint update — project_type dropped entirely in 015;
-- omitted from baseline (no column in final schema).

-- ════════════ folded: 015_project_tags.sql ════════════
-- tags column folded into CREATE TABLE projects in 0001_core_identity.sql;
-- project_type column was transient (added 005, dropped here) — omitted.
-- projects_tags_gin_idx created inline with CREATE TABLE in 0001.

-- ════════════ folded: 016_user_avatar_storage.sql ════════════
-- avatar_storage_key and avatar_updated_at folded into
-- CREATE TABLE users in 0001_core_identity.sql.

-- ════════════ folded: 017_user_preferences.sql ════════════
-- preferences folded into CREATE TABLE users in 0001_core_identity.sql.

-- ════════════ folded: 018_revision_sha256.sql ════════════
-- content_sha256 folded into CREATE TABLE file_revisions in 0001_core_identity.sql.
