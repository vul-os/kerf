# jewelry_findings — Parametric Findings Generator

## Overview

Two LLM tools for parametric jewellery-findings CAD:

| Tool | Write? | Purpose |
|------|--------|---------|
| `jewelry_create_finding` | yes | Append a `finding` node to a `.feature` file |
| `jewelry_list_findings`  | no  | Enumerate valid families and kinds (helper) |

Findings are the small functional components — jump rings, bails, earring
wires, brooch pins, end caps, clasps — that every real piece of jewellery
requires.  The `opFinding` worker in the occtWorker tessellates the geometry
from the emitted node spec; no geometry is computed here.

---

## Finding families and kinds

### `jump_ring`

Open or closed rings used to link components.

| Kind | Description |
|------|-------------|
| `round_open`   | Circular ring, gap at cut point |
| `round_closed` | Circular ring, fully closed (soldered) |
| `oval_open`    | Oval / elongated ring, open |
| `oval_closed`  | Oval / elongated ring, closed |

Key parameters:
- `wire_gauge_mm` — wire diameter.
- `inner_diameter_mm` — inner opening (must be > `wire_gauge_mm`).
- `aspect_ratio` — oval kinds only: length ÷ width ratio (≥ 1.0).  Default 1.0.
- `quantity` — batch count.  Default 1.

---

### `bail`

Pendant bails — the loop that hangs a pendant from a chain.

| Kind | Description |
|------|-------------|
| `pinch`   | Two spring arms grip the pendant edge |
| `snap`    | Spring-tab clip-on bail |
| `glue_on` | Flat adhesive-pad bail; uses `pad_width_mm` |
| `loop`    | Classic bent-wire loop bail |

Key parameters:
- `body_length_mm`, `body_width_mm` — bail body size.
- `loop_inner_diameter_mm` — inner loop diameter.
- `pad_width_mm` — `glue_on` only: adhesive pad width.

---

### `ear_finding`

Earring finding types.

| Kind | Description |
|------|-------------|
| `fish_hook`      | Shepherd's hook / French wire |
| `lever_back`     | Hinged lever-back closure |
| `post_butterfly` | Post with butterfly / clutch back |
| `screw_back`     | Threaded post + screw nut |
| `huggie`         | Small hinged-snap hoop (huggie hoop) |
| `kidney`         | Kidney-wire (self-clasping loop) |
| `ear_nut`        | Clutch / nut sold separately for posts |

Key parameters:
- `wire_gauge_mm` — wire or post diameter.
- `hook_length_mm` / `hook_width_mm` — fish_hook, kidney: hook dimensions.
- `post_length_mm` / `post_diameter_mm` — post types.
- `inner_diameter_mm` — huggie: hoop inner diameter.

Aliases: `shepherd` → `fish_hook`, `butterfly` / `clutch_back` → `post_butterfly`,
`kidney_wire` → `kidney`.

---

### `pin_finding`

Brooch and pin findings.

| Kind | Description |
|------|-------------|
| `pin_stem`       | Spring-coil-based pin stem with tapered point |
| `joint`          | Rolled barrel joint for attaching pin stem to body |
| `catch_rotating` | Rotating-frame catch |
| `catch_roller`   | Roller catch |
| `stick_pin`      | Decorative nail / stick-pin with guard cap |

Key parameters:
- `stem_length_mm` — `pin_stem` / `stick_pin`: stem length.
- `joint_diameter_mm` — `joint`: barrel outer diameter.
- `safety_catch` — `catch_*`: add secondary safety catch.  Default `false`.

Aliases: `rotating_catch` → `catch_rotating`, `roller_catch` → `catch_roller`,
`nail_pin` → `stick_pin`.

---

### `end_cap`

Connectors, cord ends, ribbon clamps, and linking elements.

| Kind | Description |
|------|-------------|
| `glue_in`       | Cup-shaped glue-in end cap with attached loop |
| `crimp`         | Crimp tube end cap |
| `cord_end`      | Glue-and-crimp cord end cap |
| `ribbon_clamp`  | Toothed ribbon clamp |
| `connector_link` | Single oval connector link |
| `figure_8`      | Figure-8 double-ring connector |
| `split_ring`    | Helical coil split ring (2.25 turns) |

Key parameters:
- `cap_inner_diameter_mm` — `glue_in` / `crimp`: inner opening.
- `cap_length_mm` — `glue_in` / `crimp`: depth.
- `cord_diameter_mm` — `cord_end`: cord outer diameter.
- `ribbon_width_mm` — `ribbon_clamp`: ribbon width.
- `ring_inner_diameter_mm` — `figure_8` / `split_ring`: ring inner diameter.

Aliases: `cord_end_cap` → `cord_end`.

---

### `clasp`

Clasp mechanisms (distinct from the clasps in `jewelry_chain`).

| Kind | Description |
|------|-------------|
| `hook_and_eye`  | Classic hook + eye closure |
| `magnetic`      | Disc-magnet push-fit clasp |
| `s_clasp`       | S-shaped wire clasp |
| `barrel`        | Screw barrel / torpedo clasp |
| `slide_lock`    | Slide-lock box clasp |

Key parameters:
- `body_length_mm` — `hook_and_eye` / `s_clasp` / `slide_lock`: body length.
- `magnet_diameter_mm` — `magnetic`: disc magnet diameter.
- `barrel_diameter_mm` — `barrel`: outer barrel diameter.

Aliases: `torpedo` → `barrel`, `hook_eye` → `hook_and_eye`, `s_hook` → `s_clasp`.

---

## Node-spec schema

Every `jewelry_create_finding` call appends a node of the form:

```json
{
  "id":            "finding-1",
  "op":            "finding",
  "family":        "<family>",
  "kind":          "<kind>",
  "wire_gauge_mm": 1.0,
  "finding_hints": { ... }
}
```

The `finding_hints` dict contains family-and-kind-specific geometry hints
consumed by the `opFinding` operator.  Common hint keys include:

| Key | Present in |
|-----|-----------|
| `inner_diameter_mm`, `outer_diameter_mm` | jump_ring, end_cap (glue_in/crimp), clasp |
| `open`, `profile` | jump_ring |
| `body_length_mm`, `body_width_mm` | bail, pin_finding (catch), clasp (hook_and_eye/s_clasp/slide_lock) |
| `loop_inner_diameter_mm` | bail, ear_finding (lever_back/kidney), end_cap, clasp |
| `hook_length_mm`, `hook_width_mm`, `curl_radius_mm` | ear_finding fish_hook |
| `post_length_mm`, `post_diameter_mm` | ear_finding post types |
| `butterfly_span_mm` | ear_finding post_butterfly |
| `thread_pitch_mm` | ear_finding screw_back, clasp barrel |
| `stem_length_mm` | pin_finding pin_stem / stick_pin |
| `barrel_outer_diameter_mm`, `barrel_inner_diameter_mm` | pin_finding joint, clasp barrel |
| `magnet_diameter_mm`, `cap_outer_diameter_mm` | clasp magnetic |
| `cord_diameter_mm` | end_cap cord_end |
| `ribbon_width_mm`, `tooth_count` | end_cap ribbon_clamp |
| `coil_turns`, `coil_gap_mm` | end_cap split_ring |

---

## Workflow examples

### Earring set with lever-back findings
```
jewelry_create_finding(
  file_id=<fid>,
  family="ear_finding",
  kind="lever_back",
  wire_gauge_mm=0.8
)
```

### Jump rings for assembly
```
jewelry_create_finding(
  file_id=<fid>,
  family="jump_ring",
  kind="round_open",
  wire_gauge_mm=1.0,
  inner_diameter_mm=5.0,
  quantity=20
)
```

### Magnetic clasp for a necklace
```
jewelry_create_finding(
  file_id=<fid>,
  family="clasp",
  kind="magnetic",
  wire_gauge_mm=0.8,
  magnet_diameter_mm=8.0
)
```

### Glue-in end caps for cord ends
```
jewelry_create_finding(
  file_id=<fid>,
  family="end_cap",
  kind="cord_end",
  wire_gauge_mm=0.5,
  cord_diameter_mm=3.0
)
```

---

## Notes

- All dimensions are in **millimetres**.
- `wire_gauge_mm` is required for every finding; typical range 0.3–3.0 mm.
- Use `jewelry_list_findings` (read-only) to enumerate all valid families and
  kinds without writing to the file.
- The `opFinding` worker in occtWorker tessellates the node geometry; no OCCT
  calls are made at spec-generation time.
- FeatureView inspector panel entries for findings are **deferred** — nodes
  appear in the feature tree but do not yet show a dedicated findings property
  panel in the UI.
