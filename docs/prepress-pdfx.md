# Prepress PDF/X & Dieline Export

> Convert packaging dielines and graphic artwork to print-ready PDF/X-3 format with CMYK colour separation and bleed/trim-mark geometry.

**Module**: `packages/kerf-packaging/src/kerf_packaging/dieline.py`
**Shipped**: Wave 9D4
**LLM tools**: `packaging_dieline_export`, `packaging_dxf_export`

---

## What it is

Packaging artwork must reach the print house as PDF/X-3 or PDF/X-1a with registered cut-and-fold lines, correct bleed, and device-independent colour. Getting colour profiles wrong causes ink-gamut shifts; missing bleed causes white-edge slivers after guillotining. This page covers the prepress pipeline: dieline geometry → annotated flat layout → DXF (for die-cutting) and PDF/X (for print).

## How to use it

### From chat

> "Export my cereal-box dieline as a PDF/X-3 with 3 mm bleed and CMYK colour profile. Also output a DXF for the die-cutter."

### From Python

```python
from kerf_packaging.dieline import Dieline, DieLine, LineKind, validate_dieline

dieline = Dieline(
    panels=[],
    lines=[
        DieLine(x0=0, y0=0, x1=300, y1=0, kind=LineKind.CUT),
        DieLine(x0=0, y0=100, x1=300, y1=100, kind=LineKind.FOLD),
    ],
    width=300.0, height=200.0,
    material="sbs", units="mm"
)
warnings = validate_dieline(dieline)
print("Warnings:", warnings)
```

### From an LLM tool spec

```json
{"dieline_id": "<uuid>", "format": "dxf",
 "bleed_mm": 3.0, "trim_marks": true,
 "colour_profile": "ISO_Coated_v2"}
```

## How it works

The `Dieline` data model stores all geometry as 2D line segments tagged by `LineKind`: `cut` (outer boundary), `fold` (crease), `score` (half-cut), and `perf` (perforation). The DXF exporter maps line kinds to layers (`0`, `FOLD`, `SCORE`, `PERF`). The PDF/X-3 exporter embeds trim-box and bleed-box annotations in the page dictionary, converts RGB panel artwork to CMYK via the chosen ICC profile, and sets the `GTS_PDFXVersion` key to `PDF/X-3:2002`. `validate_dieline` checks for non-closed cut boundaries, overlapping fold/cut intersections, and panel-to-line coverage gaps.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `validate_dieline(dieline)` | `list[str]` | Sanity-check warnings |
| `Dieline(panels, lines, width, height, material, units)` | `Dieline` | Flat-layout data model |
| `DieLine(x0, y0, x1, y1, kind)` | `DieLine` | Single line segment |

## Example

```python
from kerf_packaging.dieline import validate_dieline, Dieline, DieLine, LineKind

d = Dieline(panels=[], lines=[
    DieLine(0,0,200,0,LineKind.CUT),
    DieLine(200,0,200,150,LineKind.CUT),
    DieLine(200,150,0,150,LineKind.CUT),
    DieLine(0,150,0,0,LineKind.CUT),
    DieLine(0,75,200,75,LineKind.FOLD),
], width=200, height=150, material="sbs", units="mm")
print(validate_dieline(d))  # [] — closed cut + one fold
```

## Honest caveats

PDF/X-3 output requires a PDF writer library (`reportlab` or `pikepdf`); the module checks for availability at runtime and falls back to DXF-only export if neither is installed. ICC profile embedding uses the profile data embedded in Kerf's asset bundle — only ISO Coated v2 and sRGB are included. Full imposition (multi-up step-and-repeat, mark-and-bleed) is not implemented.

## References

- ISO 15930-6:2003 — PDF/X-3 specification.
- FOGRA 39 / ISO 12647-2:2013 — CMYK printing standards for coated paper.
