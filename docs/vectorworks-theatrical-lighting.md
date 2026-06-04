# Theatrical Lighting Plot

> Position IES-profiled fixtures on a lighting plot and simulate illuminance at any point on stage.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/render/theatrical_lighting.py`
**Shipped**: Wave 9B4
**LLM tools**: `render_theatrical_lighting_plot`, `render_parse_ies_file`

---

## What it is

The theatrical lighting module stores a lighting plot as a set of `TheatricalFixture` objects (position, aim point, IES photometric profile, colour temperature) and evaluates the illuminance (lux) at an arbitrary point on the stage. IES files (IESNA LM-63) are parsed to extract the candela distribution over polar and azimuth angles.

## How to use it

### From chat

> "Add a 1200W Fresnel at position (2, 5, 6) aimed at the stage centre. What is the illuminance at (0, 0, 0.9)?"

### From Python

```python
from kerf_cad_core.render.theatrical_lighting import (
    TheatricalFixture, TheatricalLightingPlot,
    read_ies_file, ies_candela_at,
)

with open("fresnel_1200w.ies") as f:
    ies = read_ies_file(f.read())

fixture = TheatricalFixture(
    position=(2.0, 5.0, 6.0),
    aim_point=(0.0, 0.0, 0.9),
    ies=ies,
    color_temp_K=3200,
    dimmer=1.0,
)
plot = TheatricalLightingPlot(fixtures=[fixture])
lux = plot.illuminance_at((0.0, 0.0, 0.9))
print(f"{lux:.1f} lux at stage centre")
```

### From an LLM tool spec

```json
{"tool": "render_theatrical_lighting_plot", "input": {"fixtures": [{"position": [2, 5, 6], "aim_point": [0, 0, 0.9], "ies_file": "fresnel_1200w.ies", "dimmer": 1.0}], "query_point": [0, 0, 0.9]}}
```

## How it works

`read_ies_file` parses the LM-63 format: it reads the candela table over (vertical angle, horizontal angle) grid points. `ies_candela_at` interpolates bilinearly in polar coordinates. The illuminance at a target point is computed as `E = I(θ, φ) × cos(θ_i) / d²`, where `θ_i` is the angle of incidence at the surface and `d` is the distance from fixture to point.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `read_ies_file(content)` | `IesPhotometricFile` | Parse IES LM-63 file |
| `ies_candela_at(ies, v_deg, h_deg)` | `float` | Candela at given angles |
| `TheatricalLightingPlot.illuminance_at(point)` | `float` | Lux at point from all fixtures |

## Example

```python
lux = plot.illuminance_at((0.0, 0.0, 0.9))
# 847.3 lux at stage centre
```

## Honest caveats

The inverse-square law calculation is a direct illuminance model; inter-reflections from stage floor, cyclorama, and side walls are not simulated. Colour rendering, colour temperature conversion, and beam edges (flat vs. soft-edge Fresnels) are not modelled beyond the IES candela table. Dynamic effects (follow spots, gobos, moving heads) are not supported.

## References

- IESNA LM-63-02, *Standard File Format for Electronic Transfer of Photometric Data*.
- Smith, *Stage Lighting Design*, Crowood Press (2007), Ch. 8.
