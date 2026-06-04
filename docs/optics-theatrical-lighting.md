# Theatrical Lighting Design

> Lay out stage lighting rigs with IES photometric data, beam angles, and coverage maps — for theatre, film, and live event production.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/render/theatrical_lighting.py`
**Shipped**: Wave 9
**LLM tools**: `lighting_theatrical_plot`

---

## What it is

Theatrical lighting design requires knowing which fixtures illuminate which stage areas, how beams overlap, and whether coverage is uniform. This module provides IES photometric file parsing, candela-at-angle queries, fixture layout management, and a coverage rendering engine that computes the illuminance (lux) at any point on a stage deck from a full lighting rig.

Engineers and lighting designers use it to pre-visualise a rig before the hang, check throw distances, and verify colour-mixing coverage for key areas. The output is a 2D lux map (bird's-eye or cross-section) that can be exported as SVG or PNG.

## How to use it

### From chat (natural language)

> "Show me the coverage map for 6 ETC Source Four fixtures at 5m trim height, 30° field angle, over a 10m x 8m stage"

The LLM calls `lighting_theatrical_plot` with the rig layout.

### From Python

```python
from kerf_cad_core.render.theatrical_lighting import (
    read_ies_file, TheatricalFixture, TheatricalLightingPlot,
    ies_candela_at,
)

# Parse IES photometric file
with open("source_four_36.ies") as f:
    ies = read_ies_file(f.read())

# Create fixtures
fixtures = [
    TheatricalFixture(ies=ies, position=(2,0,5), aim=(0,0,0), dimmer=1.0),
    TheatricalFixture(ies=ies, position=(-2,0,5), aim=(0,0,0), dimmer=0.8),
]

plot = TheatricalLightingPlot(fixtures=fixtures, stage_bounds=(-5,-4,5,4))
lux_map = plot.render_floor_lux(resolution=100)
print(f"Centre lux: {lux_map.centre_lux:.1f}")
```

### From an LLM tool spec

```json
{"tool": "lighting_theatrical_plot", "stage_width_m": 10, "stage_depth_m": 8,
 "trim_height_m": 5, "fixture_type": "source_four_36", "n_fixtures": 6}
```

## How it works

IES files encode the candela distribution of a luminaire as a polar matrix of intensity values (angles in vertical and horizontal planes). `ies_candela_at(theta, phi)` interpolates this matrix to give the intensity in any direction. For each fixture, the illuminance at a floor point p is computed as `E = I(θ) × cos(α) / d²`, where θ is the angle from the beam axis, α is the angle of incidence at the floor, and d is the throw distance (inverse-square law).

All fixture contributions are summed to give the total illuminance map.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `read_ies_file(content)` | `IesPhotometricFile` | Parse IES photometric data |
| `ies_candela_at(ies, theta, phi)` | `float` | Candela at angle |
| `TheatricalLightingPlot.render_floor_lux(resolution)` | `LuxMap` | Floor illuminance map |

`IesPhotometricFile` fields: `candela_matrix`, `vertical_angles`, `horizontal_angles`, `lumens`, `lamp_watts`.
`LuxMap` fields: `data` (n×n float array), `centre_lux`, `min_lux`, `max_lux`, `uniformity_ratio`.

## Example

```python
ies_candela_at(ies, theta=30.0, phi=0.0)  # candela at 30° from beam axis
```

## Honest caveats

The illuminance model uses the inverse-square law and Lambert cosine law only — no interreflections, no coloured beam mixing (additive RGB must be summed manually per channel), no atmospheric haze or fog effects. IES files with non-standard goniometer types (Type B or C with non-uniform angle increments) may parse incorrectly — check the angle array lengths. Absolute calibration of lux values depends on the accuracy of the IES lumens data, which varies by fixture and dimmer level.

## References

- Illuminating Engineering Society (2019). LM-63-19: IES Standard File Format for the Electronic Transfer of Photometric Data.
- Rea (2000). *IESNA Lighting Handbook*, 9th ed. Illuminating Engineering Society.
