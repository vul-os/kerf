# kerf-hvac — HVAC Duct Fabrication

## Overview

The `kerf-hvac` package provides computational tools for HVAC duct system
design and sheet-metal fabrication, following ASHRAE and SMACNA standards.

## Capabilities

### Duct Sizing (`hvac.size_duct`)

Selects the smallest standard duct size that satisfies a given airflow at
a maximum velocity using the **ASHRAE velocity method**.

Standard sizes use a 25 mm modular grid (rectangular and round).  Aspect
ratio is limited to 4:1 per ASHRAE recommendations.

**Typical velocity ranges (ASHRAE):**

| Application             | Supply (FPM) | Return (FPM) |
|-------------------------|-------------|-------------|
| Main supply trunk       | 1200–2500   | 600–1500    |
| Branch ducts            | 700–1800    | 500–1200    |
| Final outlets           | 400–800     | 300–600     |

**Example:**
```
hvac.size_duct(airflow_cfm=1000, max_velocity_fpm=2000)
→ { width_mm: 250, height_mm: 200, actual_velocity_fpm: 1883, aspect_ratio: 1.25 }
```

### Pressure Drop (`hvac.pressure_drop`)

Computes **Darcy-Weisbach major loss** for a straight duct run:

    ΔP = f · (L/D_h) · (ρ v² / 2)

The friction factor `f` is solved via the Colebrook-White equation (exact
iterative method) for turbulent flow; laminar flow uses `f = 64/Re`.

Minor losses for fittings are added using `ΔP_minor = K · P_v`.

**Supported fitting types:**

| ID                  | Description                                   | K      |
|---------------------|-----------------------------------------------|--------|
| `elbow_90_rect`     | 90° rectangular radius elbow (no vanes)       | 0.30   |
| `elbow_90_round`    | 90° round duct elbow (R/D = 1.5)              | 0.11   |
| `elbow_45_rect`     | 45° rectangular elbow                         | 0.15   |
| `tee_main`          | Diverging tee — main through-flow             | 0.10   |
| `tee_branch`        | Diverging tee — branch takeoff (90°)          | 0.90   |
| `reducer`           | Concentric reducer (15° half-angle)           | 0.04   |
| `cap`               | Duct terminal / end cap                       | 1.00   |
| `flex_per_metre`    | Flexible duct (per metre at full extension)   | 0.50   |

### Fitting Minor Loss (`hvac.fitting_loss`)

Quick lookup of K coefficient for a single fitting, returns loss in Pa.

### Flat Patterns

#### Rectangular Elbow (`hvac.elbow_flat_pattern`)

Generates flat (developed) metal patterns for a rectangular **radius elbow**.
Returns four panels:

- **Throat plate** — outer (long) face: rectangle `width × throat_arc_length`
- **Heel plate** — inner (short) face: rectangle `width × heel_arc_length`
- **Two cheek panels** — side faces (sector annulus, laid flat as trapezoids)

Arc lengths are computed analytically:

    L_heel   = R_throat × θ
    L_throat = (R_throat + H) × θ
    L_centre = (R_throat + H/2) × θ

Default throat radius = 1× duct height (SMACNA guidance).

#### Rectangular Reducer (`hvac.reducer_flat_pattern`)

Generates flat patterns for a concentric rectangular **reducer / transition**.
Four trapezoidal panels (top, bottom, left, right).

Slant (developed) lengths are computed analytically per SMACNA Sheet Metal
Manual, §4-3 and §4-5:

    top/bottom slant = √(L² + ((H1-H2)/2)²)
    side slant       = √(L² + ((W1-W2)/2)²)

## Data Model

A duct system is represented as:

```python
DuctSystem
  └── sections: list[DuctSection]   # straight runs
  └── fittings: list[Fitting]       # connections between sections

DuctSection(
    shape: DuctShape,               # RECTANGULAR | ROUND | OVAL
    length_mm, airflow_m3s,
    width_mm, height_mm,            # rectangular / oval
    diameter_mm,                    # round
    roughness_mm=0.09,              # galvanised steel default
    insulation_thickness_mm=25.0,
)

Fitting(
    fitting_type: FittingType,      # ELBOW | REDUCER | TEE | CAP | FLEX
    angle_deg=90.0,
    flex_length_mm,                 # for flex connectors
)
```

## Unit Conventions

All internal calculations use SI units (metres, m³/s, Pa, kg/m³).
The LLM tools accept CFM / FPM for airflow and velocity (common in practice)
and return both SI and imperial values.

Helper functions: `cfm_to_m3s`, `m3s_to_cfm`, `fpm_to_ms`, `ms_to_fpm`,
`inch_to_mm`, `mm_to_inch`.

## Physical Constants (Standard Air at 20 °C)

| Property           | Value               |
|--------------------|---------------------|
| Density            | 1.204 kg/m³         |
| Dynamic viscosity  | 1.81 × 10⁻⁵ Pa·s   |
| Kinematic viscosity| 1.50 × 10⁻⁵ m²/s   |

## References

- ASHRAE Handbook of Fundamentals (2021), Chapter 21 — Duct Design
- ASHRAE HVAC Systems & Equipment Handbook (2020), Chapter 16
- SMACNA HVAC Duct Construction Standards, 4th Edition
- SMACNA Sheet Metal Manual, 4th Edition, §4-3, §4-5
