# jewelry_bangle — Parametric Bangle, Cuff, and Torque (Torc) Builders

RhinoGold / MatrixGold parity "Bangles" wizard: closed bangles, open cuffs with spring-back compensation, twisted torques (torcs), and hinged bangles.

## When to use

Use these tools when a jeweller needs to:
- Build a rigid closed bangle sized to a wrist inner circumference (S/M/L/XL or custom mm)
- Create an open cuff with a configurable gap angle and alloy spring-back allowance
- Design a twisted torc with a cross-section that rotates (twist_turns) along the sweep path
- Build a hinged bangle split into two halves with a hinge pin and box clasp or tongue-and-groove clasp
- Compute cross-section area and second moment of area for a band profile
- Look up standard wrist sizes by inner circumference

Keywords: bangle, cuff, torque, torc, hinged bangle, closed bangle, open cuff, wrist size, inner circumference, spring-back, alloy spring-back, twist turns, finial, comfort chord, cross-section.

## Bangle types

| Type | Description |
|---|---|
| `closed_bangle` | Rigid closed hoop; inner profile round / oval / cushion / square; cross-section: round_wire, d_shape, square, knife_edge, half_round, twisted_wire |
| `open_cuff` | Open bangle with configurable gap angle; alloy spring-back allowance so cuff springs to target diameter after forming |
| `torque` | Twisted torc: cross-section swept and rotated (`twist_turns` full turns); `finial_style` controls end-cap geometry |
| `hinged_bangle` | Closed bangle in two halves; hinge pin; box clasp or tongue-and-groove clasp |

## Standard wrist sizes

Source: Pandora / Rio Grande bracelet sizing guides.

| Size | Inner circumference | Inner diameter (approx.) |
|---|---|---|
| S | 155 mm | 49.3 mm |
| M | 165 mm | 52.5 mm |
| L | 175 mm | 55.7 mm |
| XL | 185 mm | 58.9 mm |

## Cross-section area formulas (analytical)

- round_wire: A = π r², I = π r⁴ / 4
- square: A = w², I = w⁴ / 12
- d_shape: computed from half-circle + rectangle

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_create_closed_bangle` | Appends a `closed_bangle` node; required: `file_id`, `wrist_size` (S/M/L/XL) or `inner_circumference_mm`, `cross_section_profile`, `wire_diameter_mm` or `width_mm` + `thickness_mm` |
| `jewelry_create_open_cuff` | Appends an `open_cuff` node; required: `file_id`, `inner_diameter_mm`, `gap_angle_deg`, `alloy` (for spring-back); returns spring-back corrected gap |
| `jewelry_create_torque` | Appends a `torque` node; required: `file_id`, `inner_diameter_mm`, `twist_turns`, `cross_section_profile`; optional `finial_style` (ball / cone / flat / marquise) |
| `jewelry_create_hinged_bangle` | Appends a `hinged_bangle` node; required: `file_id`, `inner_diameter_mm`, `clasp_style` (box_clasp / tongue_groove), `hinge_diameter_mm` |
| `jewelry_wrist_size_lookup` | Read-only: convert between wrist size name and inner circumference/diameter; supports inverse (diameter → nearest size) |

## Example

Jeweller: "Build a 4 mm D-shape cuff bangle in 18k yellow gold, medium wrist."

1. `jewelry_wrist_size_lookup` — size=`M` → inner_circumference_mm=165, inner_diameter_mm=52.5
2. `jewelry_create_open_cuff` — file_id=`<id>`, inner_diameter_mm=52.5, gap_angle_deg=30, alloy=`18k_yellow` → spring-back correction applied; effective_gap_angle_deg=32.1
