-- Add 'print' to the files.kind enumeration so 3D-print slicing configuration
-- files (.print, JSON) can live alongside the meshes they reference.
--
-- A 'print' file holds a JSON document of the shape:
--
--   { "version": 1,
--     "mesh_ref": "/models/bracket.stl",
--     "settings": {
--       "layer_height": 0.2,
--       "infill_density": 20,
--       "perimeters": 3,
--       "retraction_enabled": true,
--       "print_temperature": 200,
--       "bed_temperature": 60
--     } }
--
-- Slicing is performed by the kerf-slicing plugin (CuraEngine subprocess,
-- AGPLv3 — called as a separate process so the hosted service stays
-- MIT-compatible). See packages/kerf-slicing/README.md for the full
-- licensing rationale.
--
-- Storing print configs as a file kind (rather than a companion table) makes
-- them queryable, restorable via file_revisions, and shareable on Workshop.
-- Re-adds files_kind_check with the full cumulative kind list (as of 058)
-- plus 'print' — must carry every prior kind forward or this migration would
-- silently drop tool/plc_st/quadmesh/etc.

alter table files drop constraint if exists files_kind_check;
alter table files add constraint files_kind_check check (
    kind in ('file','folder','assembly','step','drawing','sketch','part','feature','circuit','equations','material','simulation','script','step-ref','assembly_lock','canvas','schedule','view','sheet','duct','pipe','conduit','subd','mesh','render','section','cam_layered','tool','plc_st','quadmesh','print')
);
