# jewelry_engraving — Engraving, Monogram, and Signet Tools

Text-to-vector-outline generation and surface projection for engraving on curved jewelry surfaces. No OCCT required — returns node-spec dicts for the `opEngravingApply` worker handler.

## When to use

Use these tools when a jeweller needs to:
- Engrave text along a 3-D guide curve (e.g. ring shank outer band)
- Project hallmark / maker mark / initials onto the inner cylindrical surface of a ring band
- Create a raised or recessed monogram or signet seal on a signet ring face
- Compose a 2- or 3-initial monogram (interlocked, stacked, or encircled styles)
- Get diagnostics (minimum stroke width, recessed volume estimate, tool-clearance warning)

Keywords: engraving, monogram, signet, hallmark, text on curve, ring inscription, inner-band engraving, signet seal, monogram compose, stroke font, recessed text, raised relief, interlocked monogram, stacked monogram.

## Built-in stroke font

Single-stroke font covering:
- Uppercase A–Z
- Digits 0–9
- Hallmark symbols: period, hyphen, ampersand, copyright ©, registered ®, degree °, at @

Each glyph defined as polylines in a 1 × 1 em-square; stroke width is a fraction of the em.

## Diagnostics returned

All compute functions return a `diagnostics` sub-dict:
- `total_stroke_length_mm` — sum of all polyline segment lengths
- `recessed_volume_mm3` — approximate volume of removed material
- `min_stroke_width_mm` — smallest stroke in the rendered text
- `tool_warning` — non-empty when `min_stroke_width_mm` < minimum tool diameter threshold

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_text_on_curve` | Appends an `engraving_on_curve` node; places text along a 3-D guide curve at uniform arc-length spacing, baseline tangent to curve, normal pointing up; required: `file_id`, `text`, `curve_id` or `curve_points`, `font_size_mm` |
| `jewelry_text_on_band_inner` | Appends an `engraving_band_inner` node; projects text onto the inner cylindrical surface of a ring band; required: `file_id`, `text`, `ring_inner_diameter_mm`; optional `depth_mm` (default 0.15 mm), `font_size_mm` (default 0.8 mm), `circumferential_position` (centre / offset_deg) |
| `jewelry_signet_seal` | Appends a `signet_seal` node; raised or recessed text + monogram on a signet face with optional border; required: `file_id`, `text`, `face_diameter_mm`, `relief_mode` (raised / recessed) |
| `jewelry_monogram_compose` | Read-only: compute 2- or 3-initial monogram vector outlines; styles: `interlocked`, `stacked`, `encircled`; returns outline polylines suitable for `jewelry_signet_seal` |

### `jewelry_text_on_band_inner` default parameters

- `depth_mm` = 0.15 mm (industry standard for laser hallmark)
- `font_size_mm` = 0.8 mm
- Hallmark / fineness stamp placement: centre of inner band circumference

## Example

Jeweller: "Inscribe 'With Love' on the inside of a US size 7 ring, 1 mm deep font."

1. Compute inner diameter: ring size 7 → 17.35 mm inner diameter
2. `jewelry_text_on_band_inner` — file_id=`<id>`, text=`With Love`, ring_inner_diameter_mm=17.35, depth_mm=0.15, font_size_mm=1.0
   → diagnostics: min_stroke_width_mm=0.18, no tool_warning

Jeweller: "Create a three-initial interlocked monogram A-J-K for a signet ring."

1. `jewelry_monogram_compose` — initials=`AJK`, style=`interlocked`, size_mm=8 → outline polylines
2. `jewelry_signet_seal` — file_id=`<id>`, text=``, outline=`<from step 1>`, face_diameter_mm=12, relief_mode=`recessed`
