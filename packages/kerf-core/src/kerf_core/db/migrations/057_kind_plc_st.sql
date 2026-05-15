-- Add 'plc_st' to the files.kind enumeration for IEC 61131-3 Structured Text files.
-- A .plc.st file stores ST source code for PLC programming. Tier 1 support:
-- syntax-highlighted Monaco editor + offline lint via MATIEC parser.
-- Tier 2 (deferred): simulated execution via POST /run-plc-sim.

alter table files drop constraint if exists files_kind_check;
alter table files add constraint files_kind_check check (
    kind in ('file','folder','assembly','step','drawing','sketch','part','feature','circuit','equations','material','simulation','script','step-ref','assembly_lock','canvas','schedule','view','sheet','duct','pipe','conduit','subd','mesh','render','section','cam_layered','tool','plc_st')
);
