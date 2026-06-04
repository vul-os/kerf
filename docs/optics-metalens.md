# Metalens Design

> Design flat diffractive metalenses with hyperbolic phase profiles and pillar look-up tables — for compact imaging systems, AR/VR, and THz optics.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/optics/metalens.py`
**Shipped**: Wave 9
**LLM tools**: `optics_design_metalens`, `optics_metalens_chromatic_efficiency`

---

## What it is

A metalens is a flat optical element patterned with sub-wavelength nanostructures (pillars, fins, or holes) that impart a spatially varying phase shift to transmitted light. Unlike a conventional refracting lens, its focusing power is purely diffractive, so it can be fabricated on a flat substrate — enabling ultra-thin, lightweight lenses for phone cameras, AR glasses, LiDAR, and THz imaging.

This module designs hyperbolic phase-profile metalenses: the required phase at radius r is φ(r) = -2π/λ(√(r² + f²) - f), which maps to a pillar geometry via a precomputed look-up table (LUT) of pillar radius vs. phase shift. Given a wavelength, focal length, aperture diameter, and pillar material, it outputs the full pillar layout (number of zones, per-ring radii and pillar radii) and estimates diffraction efficiency.

## How to use it

### From chat (natural language)

> "Design a TiO2 metalens, f=2mm, diameter=1mm, wavelength 532nm"

The LLM calls `optics_design_metalens` and returns a `MetalensDesign`.

### From Python

```python
from kerf_cad_core.optics.metalens import (
    MetalensSpec, design_hyperbolic_metalens,
    metalens_efficiency_at,
)

spec = MetalensSpec(
    focal_length_mm=2.0,
    diameter_mm=1.0,
    wavelength_nm=532.0,
    material="TiO2",
    substrate="SiO2",
    pillar_height_nm=600.0,
)
design = design_hyperbolic_metalens(spec)
print(f"Zones: {design.n_zones}")
print(f"Pillars: {len(design.pillars)}")
print(f"Efficiency at 532nm: {metalens_efficiency_at(design, 532):.1%}")
```

### From an LLM tool spec

```json
{"tool": "optics_design_metalens", "focal_length_mm": 2.0,
 "diameter_mm": 1.0, "wavelength_nm": 532, "material": "TiO2"}
```

## How it works

The required phase at each pillar position is computed from the hyperbolic phase profile. A look-up table maps phase (0–2π) to pillar radius by interpolating precomputed RCWA (rigorous coupled-wave analysis) simulation data for the chosen material and wavelength. Each Fresnel zone is assigned pillars at positions where the accumulated phase equals the LUT value. Diffraction efficiency is estimated from the LUT amplitude transmission values.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `design_hyperbolic_metalens(spec)` | `MetalensDesign` | Full pillar layout |
| `metalens_efficiency_at(design, wavelength_nm)` | `float` | Diffraction efficiency at wavelength |

`MetalensDesign` fields: `n_zones`, `pillars` (List[NanoPillar]), `phase_at_r(r_mm)`, `efficiency_map`.
`NanoPillar` fields: `r_mm`, `pillar_radius_nm`, `phase_rad`.
`MetalensSpec` fields: `focal_length_mm`, `diameter_mm`, `wavelength_nm`, `material`, `pillar_height_nm`.

## Example

```python
eff = metalens_efficiency_at(design, wavelength_nm=550)
print(f"Off-design efficiency at 550nm: {eff:.1%}")  # drops ~30% off-wavelength
```

## Honest caveats

The LUT is precomputed for specific material/wavelength combinations (TiO2 at 532nm, GaN at 450nm, Si at 940nm). Other combinations require running RCWA simulations externally and providing the LUT. Metalenses are highly chromatic — efficiency drops sharply at off-design wavelengths, and achromatic metalens design requires multi-resonance pillars not currently implemented. Fabrication constraints (minimum pillar radius, aspect ratio) are checked by the spec but not enforced in the LUT.

## References

- Khorasaninejad et al. (2016). "Metalenses at visible wavelengths: Diffraction-limited focusing and subwavelength resolution imaging." *Science* 352(6290).
- Chen et al. (2018). "A review of metasurfaces: Physics and applications." *Reports on Progress in Physics* 81(2).
