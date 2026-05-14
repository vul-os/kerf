-- Add 'tool' to the files.kind enumeration for CNC tool definition files.
-- A .tool file stores a JSON tool record (ball-end mill, flat-end mill, etc.)
-- with geometry + feeds/speeds so CAM jobs can reference tools by id rather
-- than hard-coding raw parameters.

alter table files drop constraint if exists files_kind_check;
alter table files add constraint files_kind_check check (
    kind in ('file','folder','assembly','step','drawing','sketch','part','feature','circuit','equations','material','simulation','script','step-ref','assembly_lock','canvas','schedule','view','sheet','duct','pipe','conduit','subd','mesh','render','section','tool')
);
