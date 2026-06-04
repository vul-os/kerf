# Vortex Lattice Method — Wing Aerodynamics

*Domain: Aerospace · Module: `packages/kerf-aero/src/kerf_aero/vlm_viscous.py` · Shipped: Wave 9*

## Overview

Prandtl-Glauert-corrected Vortex Lattice Method (VLM) with viscous drag augmentation via strip theory. Computes spanwise lift distribution (horseshoe vortex lattice), induced drag (Trefftz-plane integration), viscous profile drag (integrated 2-D Cl-based Cd), Karman-Tsien compressibility correction, and wave drag estimate at transonic Mach numbers. Used for wing sizing, induced drag optimisation, and span-load studies.

## When to use

- Computing lift curve slope (CLα), induced drag, and span efficiency for a wing.
- Comparing taper ratio and twist distributions for minimum induced drag.
- Estimating total drag polar for performance analysis up to Mcr.

## API

```python
from kerf_aero.vlm_viscous import aero_vlm_full

result = aero_vlm_full(
    wing={
        "span_m": 10.0,
        "chord_root_m": 1.5,
        "chord_tip_m": 0.75,
        "sweep_deg": 25.0,
        "twist_deg": -2.0,
        "airfoil": "naca2412",
    },
    alpha_deg=4.0,
    Mach=0.3,
    n_span=16,
    n_chord=4,
)

print(result["CL"], result["CD_induced"], result["CD_viscous"])
print(result["spanwise_cl"])  # per-strip lift coefficients
```

## LLM tools

`aero_vlm_wing`

## References

- Katz & Plotkin, *Low-Speed Aerodynamics*, 2nd ed. (2001), ch. 12.
- Drela, *Flight Vehicle Aerodynamics* (2014).

## Honest caveats

VLM is a linearised potential flow method: it does not predict flow separation, stall, or boundary-layer effects. Viscous drag is estimated from 2-D airfoil polars via strip theory, which underestimates induced-viscous interaction near wing tips. For high-angle-of-attack or separated flow, use the CFD path. Fuselage and nacelle interference are not modelled.
