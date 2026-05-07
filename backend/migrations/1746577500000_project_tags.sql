-- Drop the project_type enum; replace with free-form `tags TEXT[]`.
--
-- A single enum lied about reality: most real projects are multi-domain
-- (a drone is mechanical + electronics + drawings; a robot adds firmware;
-- jewelry overlaps with surfacing). Free-form tags let users mix and match
-- without us pre-declaring every cross-product. The API is already permissive
-- on file kinds (any kind may be created in any project — the type only
-- filtered the UI menu), so dropping the enum is purely additive at the
-- product level.
--
-- Migration is destructive: backfill existing project_type values into a
-- 1-element tags array, then drop the column. No reversal SQL — the user
-- has authorized aggressive migrations.

alter table projects add column tags text[] not null default '{}';
update projects set tags = array[project_type] where project_type is not null;
alter table projects drop constraint if exists projects_project_type_check;
alter table projects drop column project_type;
create index if not exists projects_tags_gin_idx on projects using gin (tags);
