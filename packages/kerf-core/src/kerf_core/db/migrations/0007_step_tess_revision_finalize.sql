-- 0007_step_tess_revision_finalize.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 047_step_tess_input_spec.sql ════════════
-- input_spec and content_sha256 folded into CREATE TABLE step_tessellation_jobs
-- in 0004_library_artifacts_tokens.sql.
-- derived_artifacts_derived_kind_check updated to include 'step_mesh' inline
-- in CREATE TABLE derived_artifacts in 0004_library_artifacts_tokens.sql.

-- ════════════ folded: 048_revision_compaction.sql ════════════
-- content_codec folded into CREATE TABLE file_revisions in 0001_core_identity.sql.
-- file_revisions_file_sha256_idx, file_revisions_parent_revision_id_idx, and
-- file_revisions_sha256_base_idx created inline with CREATE TABLE in 0001.

-- ════════════ folded: 049_revision_content_ref.sql ════════════
-- file_revisions.kind check updated to include 'ref' inline in
-- CREATE TABLE file_revisions in 0001_core_identity.sql.
-- file_revisions_sha256_base_idx created inline with CREATE TABLE in 0001.
