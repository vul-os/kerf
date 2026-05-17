# Filigree and Decorative Wire — `jewelry/filigree_advanced.py`

Seven decorative wire/pattern generators for jewelry surfaces and bands.

---

## Generators

| Function | Pattern |
|----------|---------|
| `milgrain(edge_curve, *, bead_dia_mm, spacing_mm)` | Row of uniform beads along an edge curve |
| `florentine_texture(surface_region, *, line_spacing_mm, crosshatch_angle_deg)` | Hand-engraved crosshatch texture |
| `celtic_knotwork(width_mm, height_mm, *, strand_width_mm, over_under_gap_mm)` | Interlaced Celtic knot panel |
| `art_nouveau_vine(spine_curve, *, leaf_count, tendril_count, leaf_length_mm)` | Organic scrollwork vine along a spine curve |
| `persian_moorish_lace(tile_w_mm, tile_h_mm, *, repeat_x, repeat_y)` | Repeating geometric filigree tile |
| `wire_twist_rope(wire_dia_mm, strand_count, *, twist_pitch_mm, length_mm)` | Multi-strand twisted rope wire profile |
| `apply_to_band(band_params, pattern_type, *, pattern_params)` | Wrap any pattern onto a ring band geometry |

---

## Return format

All generators return:
```json
{
  "ok": true,
  "elements": [
    {"type": "bead" | "wire" | "surface_patch" | "curve",
     "geometry": {...},
     "position": [x, y, z]}
  ],
  "bounding_box": {"x_mm": ..., "y_mm": ..., "z_mm": ...},
  "estimated_wire_length_mm": 450.0,
  "notes": "..."
}
```

---

## Usage

```python
from kerf_cad_core.jewelry.filigree_advanced import (
    milgrain, celtic_knotwork, wire_twist_rope, apply_to_band
)

# Milgrain edge on a ring
edge_beads = milgrain(ring_edge_curve, bead_dia_mm=0.8, spacing_mm=0.9)

# Celtic knotwork panel 20×15 mm
panel = celtic_knotwork(20, 15, strand_width_mm=1.2, over_under_gap_mm=0.3)

# Twisted rope wire
rope = wire_twist_rope(wire_dia_mm=0.6, strand_count=3,
                       twist_pitch_mm=5.0, length_mm=200.0)

# Apply pattern to band
decorated = apply_to_band(band_params, "art_nouveau_vine",
                           pattern_params={"leaf_count": 6, "tendril_count": 4})
```

---

## Notes

- `milgrain` and `florentine_texture` are the lightest patterns; suitable for fine gold and platinum.
- `plique_a_jour` and enamel cell positioning can be combined with `persian_moorish_lace` tiles.
- `apply_to_band` handles the conformal UV mapping of the pattern to the band surface; supply `band_params` from `jewelry/watch.py` or a ring shank dict.
- No `filigree.py` or `hinge.py` standalone modules exist; hinge functionality is in `findings.py` (`compute_hinged_bangle_params`).
