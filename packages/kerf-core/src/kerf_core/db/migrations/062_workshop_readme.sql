-- 062_workshop_readme.sql
--
-- Add `readme` markdown field to the projects table so Workshop-published
-- projects carry a rich, AI-generated README (Markdown) as their primary
-- content surface.
--
-- Design notes:
--   * The field is nullable; existing rows default to NULL (no README).
--   * The README is stored as raw Markdown text.  Sanitisation is the
--     responsibility of the rendering layer (frontend: rehype-sanitize /
--     react-markdown; backend: bleach if needed before returning to API).
--   * `readme_generated_at` tracks when the field was last written so the
--     frontend can show a "generated N minutes ago" label and the backend
--     can skip re-generation when the project has not changed.
--   * `cover_storage_key` is a separate field for the auto-rendered hero
--     image (a distinct concern from the auto-captured thumbnail_storage_key
--     which is the live editor snapshot).  When present, it overrides the
--     thumbnail in the Workshop browse grid / listing hero.
--
-- Round-trip: kerf-api reads and writes both fields in the workshop publish
-- handler and the /workshop/:slug GET endpoint.

alter table projects
    add column if not exists readme               text,
    add column if not exists readme_generated_at  timestamptz,
    add column if not exists cover_storage_key    text,
    add column if not exists cover_generated_at   timestamptz;
