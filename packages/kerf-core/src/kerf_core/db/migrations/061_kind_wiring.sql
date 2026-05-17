-- Add 'wiring' to the files.kind enumeration.
-- A .wiring file stores a WireViz-style cable/harness description
-- (connectors / cables / connections) rendered to SVG by the wiring
-- viewer. The kind was exposed in the FileTree "+ New" menu and has a
-- viewer, but was never added to the CHECK constraint nor the API
-- allow-list — creating one failed silently. This closes that gap.
-- Idempotent: drop + re-add the named constraint.

alter table files drop constraint if exists files_kind_check;
alter table files add constraint files_kind_check check (
    kind in ('file','folder','assembly','step','drawing','sketch','part','feature','circuit','equations','material','simulation','script','step-ref','assembly_lock','canvas','schedule','view','sheet','duct','pipe','conduit','subd','mesh','render','section','cam_layered','tool','plc_st','quadmesh','print','gem','wiring')
);
