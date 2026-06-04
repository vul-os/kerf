# Marine Hydrodynamics and Naval Architecture

*Domain: Marine · Module: `packages/kerf-cad-core/src/kerf_cad_core/navalarch/` · Shipped: Wave 9*

## Overview

Naval architecture fundamentals: hydrostatics (displacement, waterplane area, metacentric height, stability curves), resistance estimation (Holtrop-Mennen method for ship resistance), propeller sizing (Wageningen B-series), and mooring line catenary analysis. Used for early-stage vessel design checks and stability booklets.

## When to use

- Computing vessel hydrostatics from a hull offset table or meshed hull.
- Estimating calm-water resistance and required shaft power for a vessel.
- Sizing a propeller for a given speed and installed power.
- Computing mooring line pretension and catenary geometry.

## API

```python
from kerf_cad_core.navalarch.tools import (
    hydrostatic_properties,
    holtrop_resistance,
    wageningen_propeller,
)
from kerf_cad_core.mooring.tools import catenary_mooring

# Hydrostatics from waterplane offsets
hyd = hydrostatic_properties(
    draft_m=4.5,
    waterplane_offsets=[[0,0],[5,3],[10,4.5],[15,4.5],[20,3],[25,0]],
    hull_volume_m3=850,
)
print(hyd["GM_m"])  # metacentric height

# Calm-water resistance
R = holtrop_resistance(
    L_wl=25.0, B=5.5, T=1.8, Cb=0.55,
    V_kn=12.0, displacement_t=120,
)
```

## LLM tools

`naval_hydrostatics`, `naval_resistance`, `naval_propeller`

## References

- Holtrop & Mennen, "An approximate power prediction method", *ISP* 29(335), 1982.
- Wageningen B-screw series, *NSMB Publications 132, 169, 194*.
- IMO, *International Code on Intact Stability* (2008 IS Code).

## Honest caveats

The Holtrop-Mennen method is a regression formula valid for displacement hull-forms in the range Fn < 0.45, L/B 3.9–14.9, B/T 2.1–4.0. Performance outside these bounds is extrapolation. The Wageningen B-series covers conventional screw propellers; high-skew, ducted, and contra-rotating configurations require specialist methods.
