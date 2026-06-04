# Vortex Lattice Method — Wing Aerodynamics

> Compute lift distribution, induced drag, span efficiency, and drag polar for a wing at subsonic Mach numbers.

**Module**: `packages/kerf-aero/src/kerf_aero/vlm_viscous.py`
**Shipped**: Wave 9
**LLM tools**: `aero_vlm_wing`

---

## What it is

Prandtl-Glauert-corrected Vortex Lattice Method (VLM) with viscous drag augmentation via strip theory. Computes spanwise lift distribution (horseshoe vortex lattice), induced drag (Trefftz-plane integration), viscous profile drag (integrated 2-D Cl-based Cd), Karman-Tsien compressibility correction, and wave drag estimate at transonic Mach numbers. Used for wing sizing, induced drag optimisation, and span-load studies.

## How to use it

### From chat

> "Compute CL, CD, and spanwise lift distribution for a 10 m tapered wing at 4° AoA, Mach 0.3."

### From Python

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

### From an LLM tool spec

```json
{"tool": "aero_vlm_wing", "input": {"span_m": 10.0, "chord_root_m": 1.5, "chord_tip_m": 0.75, "alpha_deg": 4.0, "Mach": 0.3}}
```

## How it works

The wing planform is divided into `n_span × n_chord` panels. Each panel is modelled as a horseshoe vortex with circulation Γ. The no-penetration boundary condition at each panel collocation point gives a linear system solved for Γ. Induced drag is computed by Trefftz-plane wake integration (Kutta-Joukowski). Viscous drag is added per strip from 2-D Cl → Cd look-up. Prandtl-Glauert correction scales all aerodynamic coefficients by `1/√(1−M²)`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `aero_vlm_full(wing, alpha_deg, Mach, n_span, n_chord)` | `dict` | Full aerodynamic analysis |

Returns: `CL`, `CD_induced`, `CD_viscous`, `CD_wave`, `CL_alpha`, `span_efficiency`, `spanwise_cl`.

## Example

```python
result = aero_vlm_full(wing, alpha_deg=4.0, Mach=0.3)
# {'CL': 0.521, 'CD_induced': 0.0087, 'CD_viscous': 0.0124,
#  'span_efficiency': 0.94, 'spanwise_cl': [...]}
```

## Honest caveats

VLM is a linearised potential flow method: it does not predict flow separation, stall, or viscous boundary-layer effects. Viscous drag from strip theory underestimates induced-viscous interaction near wing tips. For high-angle-of-attack or separated flow, use the CFD path. Fuselage and nacelle interference are not modelled.

## References

- Katz & Plotkin, *Low-Speed Aerodynamics*, 2nd ed. (2001), Ch. 12.
- Drela, *Flight Vehicle Aerodynamics*, MIT Press (2014).
