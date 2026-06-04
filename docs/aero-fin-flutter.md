# Fin Flutter and Aeroelasticity

*Domain: Aerospace · Module: `packages/kerf-aero/src/kerf_aero/fin_flutter.py` · Shipped: Wave 9*

## Overview

Structural flutter analysis for rocket fins using the Theodorsen strip-theory flutter equation and the p-k flutter solver for general wing/fin configurations. Computes flutter speed (VF), flutter frequency (ωF), and the flutter index for a given fin geometry and structural properties. Also covers the doublet-lattice method (DLM) for subsonic unsteady aerodynamics via `doublet_lattice.py`.

## When to use

- Checking if a sounding rocket fin design is flutter-free at max-Q conditions.
- Estimating the flutter margin for a UAV wing panel.
- Preliminary aeroelastic sizing of a fin before full FEA-CFD coupling.

## API

```python
from kerf_aero.fin_flutter import (
    FinGeometry, FinStructure,
    theodorsen_flutter_speed,
    flutter_index,
)

fin = FinGeometry(
    semi_span_m=0.15,
    root_chord_m=0.12,
    tip_chord_m=0.06,
    sweep_deg=30.0,
    thickness_fraction=0.06,
)

struct = FinStructure(
    material="aluminium_6061",
    rho_kg_m3=2700,
    E_Pa=69e9,
    G_Pa=26e9,
)

result = theodorsen_flutter_speed(
    fin=fin,
    struct=struct,
    air_density_kg_m3=0.85,   # at altitude
)
print(result["V_flutter_ms"])
print(result["flutter_margin_above_max_q"])
```

## LLM tools

`aero_fin_flutter`, `aero_flutter_pk`

## References

- Bisplinghoff, Ashley & Halfman, *Aeroelasticity* (1955), ch. 6.
- Theodorsen, "General theory of aerodynamic instability and the mechanism of flutter", *NACA TR 496*, 1935.
- Scanlan & Rosenbaum, *Introduction to the Study of Aircraft Vibration and Flutter* (1951).

## Honest caveats

The Theodorsen strip-theory implementation assumes 2-D unsteady aerodynamics per span strip and does not account for 3-D tip relief effects, which typically raise the flutter speed by 10–20% for low-aspect-ratio fins. The structural model uses a single-mode (beam bending or torsion) approximation; coupled bending-torsion flutter requires the full p-k solver. Transonic flutter dip (Mach 0.85–1.1) is not captured by the subsonic aerodynamic model.
