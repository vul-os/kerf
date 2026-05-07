-- Add 'equations' to the files.kind enumeration so project-level parameter
-- sheets (.equations, JSON) can live alongside the rest of the project tree.
--
-- An 'equations' file holds a JSON document of the shape:
--   { "version": 1, "params": [{ "name": "h", "expr": "wall * 5", "unit": "mm" }, ...] }
-- The frontend evaluator (src/lib/equations.js) walks the params in
-- declaration order, evaluating mathjs expressions with a fresh scope, and
-- merges the resolved values into the JSCAD / .feature / .sketch eval
-- contexts so models can reference named parameters.

alter table files drop constraint if exists files_kind_check;
alter table files add constraint files_kind_check check (
    kind in ('file','folder','assembly','step','drawing','sketch','part','feature','circuit','equations')
);
