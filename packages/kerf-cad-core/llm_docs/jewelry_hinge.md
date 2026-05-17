# Hinge and Findings — `jewelry/findings.py`

Six finding families including the hinged bangle. There is no standalone `hinge.py` module — hinge geometry is `compute_hinged_bangle_params` inside `findings.py`.

---

## Finding families

| Family | Function | Description |
|--------|----------|-------------|
| Earring | `earring_finding(style, ...)` | Post, lever-back, omega, clip-on, hoop |
| Clasp | `clasp_finding(style, ...)` | Lobster, spring-ring, toggle, box, magnetic |
| Bail | `bail_finding(style, ...)` | Simple, hinged, split-ring |
| Jump ring | `jump_ring(dia_mm, wire_mm)` | Open/closed jump ring dimensions |
| Pin finding | `brooch_finding(style, ...)` | Roll-over, c-catch, trombone |
| Hinged bangle | `compute_hinged_bangle_params(...)` | Full hinge geometry for opening bangle |

---

## `compute_hinged_bangle_params`

```python
compute_hinged_bangle_params(
    inner_dia_mm: float,
    band_width_mm: float,
    band_thickness_mm: float,
    *,
    hinge_count: int = 2,
    clasp_style: str = "box",
    tolerance_mm: float = 0.1,
) -> dict
```

Returns:
```json
{
  "inner_dia_mm": 58.0,
  "hinge_count": 2,
  "hinge_pin_dia_mm": 1.2,
  "hinge_knuckle_length_mm": 4.0,
  "hinge_gap_mm": 0.1,
  "clasp_style": "box",
  "open_arc_deg": 155.0,
  "closed_arc_deg": 205.0,
  "notes": "2-knuckle hinge each side; box clasp at 180° opposite hinge axis"
}
```

---

## Usage

```python
from kerf_cad_core.jewelry.findings import (
    earring_finding, clasp_finding, compute_hinged_bangle_params
)

# Lever-back earring
ear = earring_finding("lever_back", wire_gauge=21)

# Toggle clasp, 6 mm ring
clasp = clasp_finding("toggle", ring_dia_mm=6, bar_length_mm=14)

# Hinged bangle
bangle = compute_hinged_bangle_params(
    inner_dia_mm=58, band_width_mm=10, band_thickness_mm=2,
    hinge_count=2, clasp_style="box"
)
```

---

## Notes

- All finding functions return a parameter dict; they do not produce solid geometry directly — feed to `brep_build` or a feature evaluator.
- `compute_hinged_bangle_params` is the canonical hinge calculator; there is no standalone `hinge.py` in this package.
