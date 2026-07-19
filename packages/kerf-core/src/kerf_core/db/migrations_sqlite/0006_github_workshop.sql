-- AUTO-GENERATED from ../migrations/0006_github_workshop.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

-- 0006_github_workshop.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 031_cloud_github_tokens.sql ════════════
-- Tombstone (2026-07-18): cloud_github_tokens dropped — GitHub OAuth
-- token storage was hosted-git plumbing (decisions.md 2026-07-18 "local
-- git only; no OAuth"). Zero readers/writers left in-tree (the only hit
-- was a self-contained hermetic RLS test with no production caller;
-- removed with the table — see test_rls_cloud_github_tokens.py history).
-- github_installation_id (folded here from 063_github_installation.sql via
-- 0010) went with it.

-- ════════════ folded: 032_workshop_likes.sql ════════════

-- Workshop likes: lightweight toggle table for workshop project likes.
CREATE TABLE IF NOT EXISTS workshop_likes (
    user_id    text NOT NULL,
    project_id text NOT NULL,
    created_at text NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, project_id)
);

CREATE INDEX IF NOT EXISTS workshop_likes_project_id_idx ON workshop_likes (project_id);

-- ════════════ folded: cloud_gitlab_tokens (T-152) ════════════
-- Tombstone (2026-07-18): cloud_gitlab_tokens dropped — same reasoning as
-- cloud_github_tokens above (GitLab OAuth/PAT token storage was hosted-git
-- plumbing; decisions.md 2026-07-18). Zero readers/writers left in-tree —
-- not even a test referenced this one.
