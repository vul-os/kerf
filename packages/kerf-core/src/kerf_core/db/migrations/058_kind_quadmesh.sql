-- Add 'quadmesh' to the files.kind enumeration for quad-dominant remesh files.
-- A .quadmesh file stores the structured output of Instant Meshes:
-- { version, vertices, quads, triangles, stats }.
-- Used for SubD modelling prep, downstream FEM meshing, and retopology.
-- The instant-meshes binary (MIT, https://github.com/wjakob/instant-meshes)
-- is optional — the file kind is always registered; the compute route
-- returns HTTP 503 with an install hint when the binary is absent.

alter table files drop constraint if exists files_kind_check;
alter table files add constraint files_kind_check check (
    kind in ('file','folder','assembly','step','drawing','sketch','part','feature','circuit','equations','material','simulation','script','step-ref','assembly_lock','canvas','schedule','view','sheet','duct','pipe','conduit','subd','mesh','render','section','cam_layered','tool','plc_st','quadmesh')
);
