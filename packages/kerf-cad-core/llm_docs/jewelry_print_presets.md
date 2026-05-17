# jewelry_print_presets — Castable-Resin and Wax-Printer Presets for Jewelry Casting

Per-printer build-envelope, exposure/cure data, orientation heuristics, support-contact planning, cure schedules, and investment burnout ramps for castable resins and Solidscape wax-jet patterns.

## When to use

Use these tools when a jeweller or production technician needs to:
- Look up build-envelope and layer-height settings for a specific castable-resin printer
- Get an orientation recommendation for a ring to minimise visible layer lines on the crown face
- Plan support contacts that avoid stone seats and prong faces
- Get cure schedule parameters (UV wavelength, exposure time, post-cure duration)
- Get the correct investment burnout ramp for a specific castable resin or wax

Keywords: 3D print presets, castable resin, wax jet, Formlabs, Form 3B, Form 4B, EnvisionTEC, B9 Creator, Solidscape, layer height, print orientation, ring orientation, support density, burnout ramp, dewax, burnout temperature, lost-wax casting, lost-resin casting, investment flask.

## Printer families covered

| Family | Models | Material |
|---|---|---|
| Formlabs Form 3B+ | DLP/LFS | Castable Wax 40, Castable Wax Resin, Castable Blue Resin, Castable Tough Resin |
| Formlabs Form 4B | LFS next-gen | Same resin portfolio, faster speeds |
| EnvisionTEC Micro+ | DLP | Easy Cast 2.0, EC500 |
| EnvisionTEC Ultra | High-volume DLP | Easy Cast 2.0, EC500 |
| B9 Creator | DLP | B9 Yellow, B9 Blue core series |
| B9 Core 530 | DLP | B9 Core Series 530 |
| Solidscape S300 | Wax-jet | S300 castable wax |
| Solidscape T200 | Wax-jet | T200 support + build wax |

## Orientation heuristic

For a ring shank the visible crown face should be parallel to the build platform (facing horizontally, not up the Z-axis) to minimise visible layer steps. Heuristic: orient so the largest cross-sectional span lies in the X–Y plane (top of band along X or Y, not Z).

## Investment burnout ramp (castable resins — lost-resin casting)

| Stage | Range | Rate | Duration |
|---|---|---|---|
| Warm-up | RT → 150 °C | 1 °C/min | 60–90 min |
| Dewax | 150 °C → 370 °C | 1 °C/min | ~220 min |
| Preheat | 370 °C → 732 °C | 3 °C/min | ~121 min |
| Hold | 732 °C | — | 60–120 min |
| Casting pour | varies by alloy | — | — |

Standard 3-stage ramp used for Formlabs, EnvisionTEC, and B9 castable resins. Solidscape wax follows a shorter 2-stage ramp (150 °C → 540 °C at 5 °C/min, then hold).

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_print_presets_get` | Read-only: return full preset dict for a named printer + resin combination; required: `printer` key |
| `jewelry_print_orientation` | Read-only: compute recommended build orientation for a ring or jewelry piece given its AABB; returns rotation vector, rationale, layer-line visibility score |
| `jewelry_print_support_plan` | Read-only: generate support contact points on underside faces; required: `piece_aabb`, `orientation`; optional `exclusion_zones` (stone/prong face bounding boxes), `support_density_mm` |
| `jewelry_burnout_ramp` | Read-only: return the burnout temperature ramp for a given `resin` or `wax` material; returns list of `{stage, T_start, T_end, rate_C_per_min, duration_min}` |

### Key inputs for `jewelry_print_presets_get`

- `printer` — e.g. `form_3b_plus`, `form_4b`, `envisiontec_micro_plus`, `envisiontec_ultra`, `b9_creator`, `b9_core_530`, `solidscape_s300`, `solidscape_t200`
- `resin` — optional; default is the primary castable material for that printer

### Preset output fields

- `build_volume_mm` — `{x, y, z}` build envelope
- `layer_height_um` — default layer height in microns
- `xy_resolution_um` — XY pixel resolution
- `cure_wavelength_nm` — UV wavelength for DLP printers
- `post_cure_duration_min` — recommended UV post-cure time
- `ash_content_pct` — residual ash after burnout (lower = cleaner casting)

## Example

Jeweller: "What printer settings should I use for a Form 4B with Castable Wax 40 for a ring? How do I orient it?"

1. `jewelry_print_presets_get` — printer=`form_4b`, resin=`castable_wax_40` → layer_height_um=25, xy_resolution_um=25, ash_content_pct=0.01
2. `jewelry_print_orientation` — piece_aabb={x:20,y:20,z:6}, orientation_current=[0,0,1] → recommend X-axis up; layer_line_visibility_score=0.95
3. `jewelry_burnout_ramp` — resin=`castable_wax_40` → 3-stage ramp from RT to 732 °C
