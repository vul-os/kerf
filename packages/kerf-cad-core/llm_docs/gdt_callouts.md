# GD&T Auto-Callout Proposal and Balloon Tables

Pure-Python ASME Y14.5 / ISO 1101 auto-callout engine. Given a list of classified
model features and a datum reference frame, automatically proposes feature control
frames with IT-grade tolerance magnitudes and formats a numbered balloon table for
drawing annotations. Works on top of the `gdt` module's datum/tolerance layer.

---

## When to use

Reach for this module when the user asks about:

- automatically generating GD&T callouts for a part's features
- proposing feature control frames for holes, slots, planar faces, cylinders,
  patterns, or freeform surfaces
- applying ISO 286-1 IT-grade tolerances (IT5 through IT12)
- creating a balloon-numbered drawing annotation table
- generating a GD&T drawing callout sheet from a feature list
- adjusting tolerance intent (loose / nominal / tight / precise)
- connecting datums from `gdt_apply_datum` to auto-proposed tolerances

---

## Tools

### `gdt_auto_callouts`

Auto-propose GD&T feature control frames for a list of classified model features
following ASME Y14.5 / ISO 1101 rules. Feature types supported:

| Feature type   | Proposed symbol               |
|----------------|-------------------------------|
| `hole`         | POSITION (⊕), cylindrical zone |
| `slot`         | POSITION, centre-plane zone   |
| `planar_face`  | PERPENDICULARITY ⊥ or PARALLELISM ∥ (FLATNESS if no datum) |
| `cylindrical`  | RUNOUT ↗ about axis datum (CYLINDRICITY if no datum) |
| `pattern`      | Composite POSITION ⊕           |
| `freeform`     | PROFILE_SURFACE ⌓              |

Tolerance magnitudes use ISO 286-1 IT grades; default IT7. The `intent` parameter
shifts grade: `loose` (+2), `tight` (−1), `precise` (−2). Returns proposed
`callouts` list with feature id, tolerance dict, and rationale for each.

### `gdt_callout_balloon_table`

Format a list of proposed callouts (from `gdt_auto_callouts`) as a numbered
balloon table for drawing annotations. Assigns sequential balloon numbers and
formats each callout as a feature-control-frame text string. Returns `balloons`
list `[{balloon, feature_id, callout_string, rationale}]`, formatted `text` table,
and `count`.

---

## Example

**User ask:** "I have a machined bracket with a ⌀20 mm mounting hole, a planar
bottom face, and 4 × ⌀6 mm bolt holes in a pattern. Propose GD&T callouts at
IT7 grade and give me a balloon table."

```
1. gdt_auto_callouts
     features:[
       {feature_id:"bottom-face", feature_type:"planar_face",
        orientation_datum:"A"},
       {feature_id:"main-bore",   feature_type:"hole",
        nominal_size_mm:20, primary_datum:"A", secondary_datum:"B"},
       {feature_id:"bolt-holes",  feature_type:"pattern",
        nominal_size_mm:6, pattern_count:4,
        primary_datum:"A", secondary_datum:"B"}
     ]
     datums:[{label:"A",datum_type:"PLANE"},
             {label:"B",datum_type:"AXIS"}]
     grade:"IT7"  intent:"nominal"
   → {callouts:[…], count:3, grade_used:"IT7"}

2. gdt_callout_balloon_table
     callouts:{from step 1 .callouts}
     title:"Bracket GD&T Table"
   → {balloons:[{balloon:1,…},{balloon:2,…},{balloon:3,…}],
      text:"…table…", count:3}
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- `gdt_auto_callouts` builds on the `gdt` module — datums should be created with
  `gdt_apply_datum` first for datum-type validation.
- IT grade range: IT01, IT0, IT1 through IT18. Practical machining: IT5–IT9.
- `gdt_callout_balloon_table` produces Unicode feature-control-frame symbols
  (e.g. ⊕, ⊥, ⌓) suitable for display in reports and drawing notes.
- Invalid inputs return `{ok:false, reason:...}` — never raise.
