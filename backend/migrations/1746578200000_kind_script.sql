-- Add 'script' to the files.kind enumeration so Scripting automation files
-- (.script.ts, TypeScript) can live alongside their consumers. A 'script'
-- file holds TypeScript source for a Phase 1 stub:
--
--   // .script.ts — author against the (eventual) typed `kerf.*` API.
--   // Engine (esbuild-wasm bundler in a Web Worker, fixed-RPC backend ops)
--   // is deferred to a follow-up. For now this kind exists purely so the
--   // future engine has a stable file shape to write to / read from.
--
-- Storing scripts as a file kind (rather than a companion table) keeps them
-- queryable, restorable via file_revisions, and shareable on Workshop. If
-- indexing-heavy queries emerge later we can add a sidecar table; for now
-- content lives in files.content.
--
-- Mirrors 1746577900000_kind_simulation.sql: drop the existing
-- files_kind_check, re-add with 'script' appended.
alter table files drop constraint if exists files_kind_check;
alter table files add constraint files_kind_check check (
    kind in ('file','folder','assembly','step','drawing','sketch','part','feature','circuit','equations','material','simulation','script')
);
