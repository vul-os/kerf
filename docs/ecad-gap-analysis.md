# ECAD gap analysis — T-525 step 1

**Date:** 2026-08-05. **Scope:** measure, per KiCad construct, whether the gap in
`kicad_io.py` is (a) adapter-only, (b) a small Circuit JSON extension, or (c) a genuine
IR limit — before any IR is designed. This is the deliverable; no schema was written.

## Bottom line

Of the 12 required constructs, **none** land cleanly in (c). Every one has a working
path through data the toolchain already has: Circuit JSON's own types, Kerf's existing
(informal) Python-side board extensions, or `kiutils` — a complete, already-installed
KiCad file-format parser that `kicad_io.py` simply does not use. **Recommendation:
shrink G2.** Don't design a new IR "modelled on KiCad's data model" — `kiutils` already
is that model. The real work is a reader/writer that goes through `kiutils` instead of
a 90-line hand-rolled s-expression lexer, plus formalizing Kerf's existing informal
board extensions into typed fields. See [Recommendation](#recommendation).

## Method and honesty disclosure

Real KiCad-authored files found in the repo:

- `packages/kerf-imports/tests/fixtures/Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod`
  — genuine KiCad official footprint library file (`generator pcbnew`, real
  `kicad-footprint-generator` provenance). Used as primary evidence for pad shapes,
  footprint graphics, and 3D model links.
- `packages/kerf-imports/tests/fixtures/Device.kicad_sym` — genuine KiCad official
  symbol library file. Used as evidence for symbol properties/graphics/pins.
- `packages/kerf-firmware/tests/fixtures/xcheck/*/board.kicad_pcb` (4 files, 29–39
  lines each) — hand-built test doubles for a firmware pin-mapping cross-check, not
  full pcbnew exports. Useful only for pad/net/footprint basics.
- `packages/kerf-parts/tests/fixtures/synthetic/*` — explicitly self-labelled
  synthetic (`"Synthetic test capacitor footprint 0402 — hand-authored, not from any
  upstream library"`, `KerfCap_0402.kicad_mod:6`).

**No `.kicad_pcb` or `.kicad_sch` fixture in the repo contains a zone, a group, a
locked object, a dimension, a hierarchical sheet, or a stackup block.** For those
constructs I could not test against a real repo file. I built one hand-written
synthetic board (`scripts/t525_gap_probe.py` — throwaway, not part of any test suite,
safe to delete) containing a zone with thermal-relief fill settings, a keepout zone,
a `group`, a `locked` footprint with `attr` flags, a custom pad with `primitives`, a
`gr_text`, and a `dimension`, cross-checked against the installed `kiutils` dataclasses
for correct v6/v7 syntax, and ran it through `kicad_io.py`'s actual parser rather than
just reading the source. Result: the generic lexer captures every node (`zone`,
`group`, `dimension`, `gr_text`, `locked`, `attr`, `pad`, `model` all appear in the
parsed tree), but `kicad_pcb_to_circuit_json` only ever special-cases `net`,
`footprint`, and `segment` at the top level and only reads `at`/`layer`/`tstamp`/
`fp_text` inside a footprint (`kicad_io.py:585,609,685,624-651`) — so all of the above
are silently dropped on read, confirmed by execution, not just by inspection. Beyond
that one synthetic-but-executed fixture, I also drew on two things stronger than a
hand-built fixture alone but weaker than a real board with these features: (1)
`kiutils` (v1.4.8, installed, a declared optional dependency of `kerf-imports` /
`kerf-parts`) — a third-party parser reverse-engineered against and validated by
KiCad's own test suite, not something I wrote for this task; (2) direct reading of
`kicad_io.py`/`kicad_bridge.py` source and `circuit-json`'s type definitions. **Flag
this plainly: constructs 3–7 and 9–11 in the table below (zones/pours' fill settings,
custom pad primitives beyond roundrect, teardrops, rule areas, net classes, sheets,
stackup, groups, locked, dimensions) are corroborated by format/library evidence and
the executed synthetic fixture above, not by parsing a real-world `.kicad_pcb`
containing them.** Copper pours, 3D models, and pad shapes (roundrect) are the
exceptions — those are backed by a real fixture or a real consumer module.

Files read in full: `packages/kerf-electronics/src/kerf_electronics/kicad_io.py` (773
lines), `packages/kerf-electronics/src/kerf_electronics/kicad_bridge.py` (relevant
sections), `packages/kerf-electronics/tests/test_kicad_io.py` (test list only).
`circuit-json` types read from `node_modules/circuit-json/dist/index.d.mts` (69,053
lines, grepped + read by section). `kiutils` read from the installed package
(`/opt/homebrew/anaconda3/lib/python3.13/site-packages/kiutils/`, v1.4.8).

## The crux finding: kiutils

`kicad_io.py`'s docstring states its guarantee explicitly: *"component refs, net
names, and footprint names"* survive round-trip (`kicad_io.py:13-14`). The whole file
is a **from-scratch** s-expression lexer/emitter (`kicad_io.py:27-189`) that only
handles: the standard layer table, a default `setup > rules` block, the net table,
footprint position/rotation/layer/ref/value, and straight trace segments
(`kicad_io.py:244-412`). `circuit_json_to_kicad_sch` is equally narrow: a stub
`lib_symbols` entry per footprint, symbols placed in a grid, and wire-stub/label
approximations of nets — no sheets (`kicad_io.py:417-558`). `kicad_bridge.py` builds
on the same primitives (`kicad_bridge.py:31-39` imports `_Sexp`/`_parse_sexpr` from
`kicad_io.py` directly) and documents the identical gap in its own return value:
*"Copper zones (pours) and custom design rules are not imported"*
(`kicad_bridge.py:815-818`).

Meanwhile, `kerf-imports` and `kerf-parts` already depend on **`kiutils`**
(`packages/kerf-imports/pyproject.toml`: `kicad = ["kiutils"]`; used in
`kerf_imports/kicad.py`, `kerf_imports/kicad_library.py`, `kerf_imports/plugin.py`,
`kerf_parts/adapters/kicad.py`) for KiCad *library* (symbol/footprint) import. `kiutils`
is a complete, lossless, bidirectional object model for the full modern KiCad file
format — zones with `priority`, `KeepoutSettings` (tracks/vias/pads/copperpour/
footprints as independent booleans), `FillSettings` (`thermalGap`, `thermalBridgeWidth`)
(`kiutils/items/zones.py:26-102,481-597`); pad `primitives` and a `locked` flag on both
pads and footprints (`kiutils/footprint.py:374-375,470-475,536,720-721`); `Group`
(`name`, `locked`, `id`, `members: List[str]` of *any* item id)
(`kiutils/items/common.py:562-579`); `Stackup`/`StackupLayer`/`StackupSubLayer`
(`kiutils/items/brditems.py:145,192,319`); full hierarchical sheets with multi-project
instances — `HierarchicalSheet`, `HierarchicalSheetInstance`,
`HierarchicalSheetProjectPath` (`kiutils/items/schitems.py:1222-1468`); footprint
`Attributes` with all six KiCad flags including `boardOnly` and
`allowMissingCourtyard`, which Circuit JSON's own `KicadFootprintAttributes` lacks
(`kiutils/footprint.py:41-61` vs `circuit-json:1211-1232`); and `Dimension` objects
(`kiutils/items/dimensions.py:27,121,217`).

**`kicad_io.py` uses none of this.** The KiCad-fidelity gap is not "Circuit JSON can't
express X" and it is not even fully "we'd have to write a parser for X" — a complete,
tested parser for X is one import away, already vetted well enough that a sibling
package trusts it for library import. `kicad_io.py` re-invented a much smaller wheel
for the PCB/schematic round-trip path specifically (its docstring says why: *"pure
Python; no external dependencies required"* — `kicad_io.py:16`). That trade-off is a
real design decision, not an oversight, and it's the one judgment call this report
surfaces rather than resolves: **`kiutils` is GPLv3-licensed.** That's almost
certainly why it's an optional extra for library import rather than a core dependency
of `kerf-electronics`'s PCB round-trip path. Adopting it for `kicad_io.py` buys most of
the fidelity table below essentially for free, but is a licensing decision (server-side
GPLv3 use without redistribution is normally fine; bundling it into a distributed
product is a different question), not an engineering one — flagging it for whoever
picks up the shrunk epic rather than deciding it here.

## Gap table

| # | Construct | KiCad emits it | `kicad_io.py` handles it | Representable today | Class |
|---|---|---|---|---|---|
| 1 | Copper pour geometry (poly/rect/BRep) | Yes | No (`kicad_io.py`: zero `zone`/`pour` tokens) | `pcb_copper_pour` rect/brep/polygon variants, exact match on shape/layer/net (`circuit-json:10780-11099`) | **(a)** |
| 2 | Ground planes / ground-plane regions | Yes (`zone` w/ `connect_pads` `net`=0 or fill-all) | No | `pcb_ground_plane`, `pcb_ground_plane_region` (`circuit-json:10630-10721`) | **(a)** |
| 3 | Thermal reliefs (spoke count/width/gap) | Yes (`zone > connect_pads`, `fill > thermal_gap/thermal_bridge_width`) | No | `pcb_thermal_spoke` — `spoke_count`, `spoke_thickness`, inner/outer diameter, linked to `pcb_ground_plane_id` (`circuit-json:10767-10778`); Kerf's own `tools/pour.py:62-70` already models `thermal_relief.{gap,spoke_width,spoke_count}`; `src/lib/copperPour.ts:47-54` validates the same fields | **(a)** |
| 4 | Zone fill priority (overlap ordering) | Yes (`zone > priority`) | No | Not in `circuit-json`'s `pcb_copper_pour` (checked — no `priority`/`fill_mode` field anywhere in the package). **But** Kerf's own `tools/pour.py:75-78` and `src/lib/copperPour.ts:44-45` already carry `priority` informally; `kiutils.items.zones.Zone.priority` (`zones.py:515-516`) parses it losslessly | **(b)** — one integer field to formalize |
| 5 | Custom pad primitives (single polygon, roundrect) | Yes | No (fixed circle/rect/oval assumed nowhere — `kicad_io.py` doesn't emit/parse pads at all) | `PcbSmtPadPolygon` (straight-edge points, no arcs) (`circuit-json:6209-6222`); **real fixture evidence**: `R_0805_2012Metric.kicad_mod:85-94` uses `roundrect` w/ `roundrect_rratio` | **(a)** for single-shape pads |
| 5b | Composite multi-primitive pads (KiCad's `primitives` — union of several shapes in one pad) | Yes (rare) | No | Not modelled by any single Circuit JSON pad type; `kiutils.footprint.Pad` parses the raw `primitives` list as graphics (`footprint.py:470-475,536`) but doesn't interpret union semantics either | **(b)** — niche, additive |
| 6 | Teardrops | Yes (KiCad ≥7 native `teardrop`, or historically drawn as filled polygons) | No | Kerf already generates and stores these: `tools/via_stitching.py:34-36,197-247,322-365` — `apply_teardrops` tool writes `board['teardrops']` | **(a)** via Kerf's own model, not via `circuit-json` (no teardrop type there) |
| 7 | Rule areas / keepout zones, per-restriction-type (track/via/pour/footprint) | Yes (`zone > keepout`) | No | `pcb_keepout` exists but only `rect`/`circle` shape, no restriction-type booleans (`circuit-json:9503-9600`); Kerf's `autoplace/essentials.py:470-513` already emits circle keepouts (placement-only use case, matches `pcb_keepout` shape for shape); full granularity (`tracks`/`vias`/`pads`/`copperpour`/`footprints` as independent flags) only in `kiutils.items.zones.KeepoutSettings` (`zones.py:26-102`) | **(b)** — shape+flags extension |
| 8 | Net classes + DRC dimensions (trace width, clearance, via size/drill, diff-pair) | Yes (KiCad ≥6: JSON `net_settings` inside `.kicad_pro`) | No (`kicad_io.py` never touches `.kicad_pro`; `kicad_bridge.py` builds one but only for design-rule *defaults*, `kicad_bridge.py:176-177`) | Kerf's own `tools/net_classes.py:22-28,43-58` already models exactly this (`trace_width_mm`, `clearance_mm`, `via_diameter_mm`, `via_drill_mm`, `target_impedance_ohms`) as `board.net_classes`/`board.net_class_assignments`; not in `circuit-json`'s strict schema (no `netclass`/`net_class` type found) | **(a)** via Kerf's own model; the KiCad side is plain JSON, not s-expression, so it's a JSON-merge problem, not a parser problem |
| 8b | Net-class rules as *live DRC-engine* semantics (`.kicad_dru` conditional expressions, rule precedence) | Yes | No | Kerf's `pcb_drc.py`/`drc_presets.py` apply canned named presets, not an expression evaluator for arbitrary custom rules | **Ambiguous / out of IR scope** — this is a rule-engine gap, not a data-modelling gap; storing the numbers is (a), replicating KiCad's rule language is a different project. Cannot classify cleanly as (b) or (c) without separately scoping a DRC-rule-engine task. |
| 9 | Hierarchical sheet instances, sheet pins, global/hierarchical labels | Yes | No — `circuit_json_to_kicad_sch` places all components flat in a grid, `kicad_io.py:463-558`, no sheet objects at all | Kerf's own `tools/hier_schematic.py:4-13,37-43` already models `board.sub_sheets` (id/name/file_id/position/pins), `global_labels`, `hierarchical_labels`, with sheet-path-based net union-find (`hier_schematic.py:53-70,157-189`); `circuit-json`'s `SchematicSheet` is a 3-field stub (`type`/`id`/`name`/`subcircuit_id`, `circuit-json:25041-25046`) | **(a)** base case via Kerf's model |
| 9b | Multi-instance hierarchical sheets (same sub-sheet used twice, independently-numbered reference designators) | Yes (KiCad's `instances`/`HierarchicalSheetInstance`) | No | Not in Kerf's `sub_sheets` model or `circuit-json`; fully modelled in `kiutils.items.schitems.HierarchicalSheetInstance`/`SymbolProjectInstance` (`schitems.py:903,1279,1339,1468`) | **(b)** — path/instance field addition, not new geometry |
| 10 | Board stackup (dielectric layers, εr, copper weight) + controlled-impedance flag | Yes (`.kicad_pcb setup > stackup`) | No | Kerf's `tools/flex_stackup.py` already models per-layer type/thickness/εr and a `controlled_impedance` feasibility flag (`flex_stackup.py:66-67,660-689,732`) for flex/rigid-flex; not in `circuit-json` (no `stackup`/`dielectric`/`impedance` match anywhere in the package); `kiutils.items.brditems.Stackup/StackupLayer/StackupSubLayer` (`brditems.py:145,192,319`) covers the rigid-board case Kerf's flex-only model doesn't | **(a)**/**(b)** — data exists in two Kerf-adjacent places (Kerf's flex tool, kiutils), needs unifying, not inventing |
| 11 | 3D model links (STEP/WRL, offset/scale/rotate) | Yes | No (`kicad_io.py` never emits/parses `(model ...)`) | Exact match: `KicadFootprintModel { path, offset{x,y,z}, scale{x,y,z}, rotate{x,y,z} }` (`circuit-json:1314-1331`); **real fixture evidence**: `R_0805_2012Metric.kicad_mod:95-101` and `KerfCap_0402.kicad_mod:29-32` both use exactly this shape | **(a)** — cleanest case in the table besides pours |
| 12 | Groups (arbitrary board-item collection, cross-type) | Yes (`group` token) | No | `circuit-json`'s `pcb_group` is a *different concept* — a tscircuit layout/autoplacement packing construct restricted to `pcb_component_ids` with `layout_mode`/`autorouter_configuration` (`circuit-json:10238-10298`), not an arbitrary-membership selection group; `kiutils.items.common.Group` (`name`, `locked`, `id`, `members: List[str]`) is the real KiCad shape (`common.py:562-579`) | **(b)** — needs a new, structurally trivial type; don't overload `pcb_group` |
| 13 | Locked objects (footprint/pad/track/via/text/group) | Yes (`locked` token, widespread) | No (`kicad_io.py` never reads/writes `locked` anywhere) | Not in `circuit-json` (no `locked` field found in any type) or in any Kerf Python model (grepped `kerf-electronics` — zero hits); fully parsed as a plain boolean by `kiutils` on `Pad` and `Footprint` (and `Group`) (`footprint.py:374-375,720-721`; `common.py:572-573`) | **(a)** if the IR reader goes through `kiutils` (trivial pass-through boolean); **(b)** if `circuit-json` itself must carry it standalone |
| 14 | Free-floating text objects (`gr_text`) | Yes | No (`kicad_io.py` only emits `fp_text` bound to a footprint's reference/value) | `PcbText` — `text`, `center`, `layer`, `width`, `height`, `align` (`circuit-json:6633-6645`) | **(a)** |
| 15 | Dimension objects (linear, with witness lines) | Yes | No | `PcbNoteDimension` — `from`/`to`, `text`, `offset_distance`/`offset_direction`, `font_size`, `arrow_size`, `layer` (`circuit-json:9404-9425`); also `PcbFabricationNoteDimension` | **(a)** for linear; **(b)** for radial/angular variants (not found in `circuit-json`) |
| 16 | Footprint attributes (`smd`/`through_hole`/`exclude_from_pos_files`/`exclude_from_bom`/`allow_missing_courtyard`/`board_only`) | Yes (6 flags, `kiutils.footprint.Attributes:41-61`) | No | `KicadFootprintAttributes` covers 4 of 6 — missing `allowMissingCourtyard`, `boardOnly` (`circuit-json:1211-1232`) | **(a)** for 4/6, **(b)** for the remaining 2 (plain booleans) |

## Counts

- **(a) adapter-only:** 10 of 16 rows (1, 2, 3, 5, 6, 8, 9, 11, 14, 15-linear, 16-partial;
  13 conditionally). Includes the pour case that motivated this task, plus 3D models,
  net classes, teardrops, and hierarchical sheets — all already modelled somewhere in
  Kerf's own codebase and simply not wired to `kicad_io.py`.
- **(b) small extension:** 6 rows (4, 5b, 7, 9b, 10-partial, 12, 16-partial, 15-non-linear)
  — all are additive fields or one small new flat type (groups), never new geometry
  or new conceptual machinery.
- **(c) genuine IR limit:** **0 rows.** Nothing on the required list needs modelling
  Circuit JSON (or Kerf's existing Python models, or `kiutils`) cannot reasonably carry.
- **Ambiguous, flagged rather than forced:** 1 (row 8b, DRC rule-engine semantics —
  arguably not an IR question at all).

## Recommendation

**Shrink G2.** The evidence does not support "define an IR modelled on KiCad's data
model" as a from-scratch design exercise — `kiutils` already is that model, is already
a dependency two packages over, and already round-trips everything in the table above
losslessly (that is its entire purpose: *"Simple and SCM-friendly KiCad file parser"*).
Building a parallel hand-rolled IR would be re-deriving a solved problem, with the one
open question being a licensing call (GPLv3 — see above), not a modelling one.

What T-526/T-527 should become, concretely:

1. Replace `kicad_io.py`'s reader with one built on `kiutils`'s object tree (or, if the
   GPLv3 question is decided against, extend the existing lexer — the s-expression
   grammar for zones/groups/locked/dimensions/stackup is public KiCad documentation,
   just more work to hand-roll than to import).
2. Map `kiutils` objects to Circuit JSON where a clean type already exists (pours,
   ground planes, thermal spokes, 3D models, text, pad shapes, dimensions — the (a)
   rows) and to Kerf's existing informal board extensions where those already exist
   (net classes, teardrops, sub-sheets, flex stackup) — formalizing those into typed
   fields is real but small work, not IR design.
3. Add the handful of (b) fields/types identified above (pour priority, keepout
   restriction flags, sheet-instance paths, `Group`, two footprint-attribute flags,
   non-linear dimensions).
4. Anything `kiutils` parses that has no home in (2) or (3) — the true long tail —
   goes in a passthrough bag keyed by position, exactly as T-525's original step-2
   design already specified. That part of the plan was right regardless of the IR
   question; it's the "define a whole new schema first" framing that the evidence
   doesn't support.

This is a smaller, better-specified successor to T-525/526/527: a KiCad-shaped
reader/writer over data Kerf mostly already has, not a new unified IR. T-528
(round-trip conformance vectors) and T-529–535 (front-end lowerings, consumer
migration) are largely unaffected in shape, only in size — there is less to migrate
onto if there's no new IR type hierarchy, just a richer, honestly-scoped `kicad_io.py`.
