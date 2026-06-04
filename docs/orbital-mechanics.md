# Orbital Mechanics

> Convert orbital elements, compute Hohmann and bi-elliptic delta-Vs, solve Lambert's problem, and propagate J2 perturbations.

**Module**: `packages/kerf-aero/src/kerf_aero/orbital/`
**Shipped**: Wave 9
**LLM tools**: `aero_orbital_elements_to_state`, `aero_hohmann_transfer`, `aero_lambert_solve`

---

## What it is

Two-body orbital mechanics covering: (1) element-to-state and state-to-element conversion, (2) Kepler's equation solver, (3) Hohmann and bi-elliptic transfer delta-V budgets, (4) Lambert's problem solver (Izzo method) for rendezvous and interplanetary trajectories, and (5) J2/J3/J4 secular perturbation rates for RAAN drift and perigee precession.

## How to use it

### From chat

> "Compute the delta-V for a Hohmann transfer from LEO (400 km) to GEO (35786 km)."

### From Python

```python
from kerf_aero.orbital.transfers import hohmann_delta_v
from kerf_aero.orbital.kepler import elements_to_state, propagate_kepler
from kerf_aero.orbital.lambert import lambert_izzo

# Hohmann transfer
hoh = hohmann_delta_v(r1_km=6778.0, r2_km=42164.0)
print(hoh.dv1_ms, hoh.dv2_ms, hoh.transfer_time_s)

# Convert elements to state
state = elements_to_state(a_km=6778, e=0.001, i_deg=28.5,
                           raan_deg=45, argp_deg=0, nu_deg=0)

# Lambert's problem
sol = lambert_izzo(r1_km=[6778,0,0], r2_km=[0,42164,0],
                   tof_s=5*3600, mu=398600.4418)
```

### From an LLM tool spec

```json
{"tool": "aero_hohmann_transfer", "input": {"r1_km": 6778.0, "r2_km": 42164.0}}
```

## How it works

Kepler elements-to-state: rotation matrices from RAAN (Ω), inclination (i), argument of perigee (ω) into ECI frame; radial/transverse decomposition. Lambert (Izzo): universal-variable formulation solves a scalar `τ(x)` equation for the variable `x` using Halley iterations — converges in 3–5 iterations for most geometries. J2 secular rates: analytic first-order secular rate equations for Ω̇, ω̇, Ṁ from Kozai/Brouwer theory.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `hohmann_delta_v(r1_km, r2_km)` | `HohmannResult` | Two-impulse transfer delta-Vs and TOF |
| `elements_to_state(a_km, e, i_deg, raan_deg, argp_deg, nu_deg)` | `dict` | ECI position and velocity |
| `lambert_izzo(r1_km, r2_km, tof_s, mu)` | `LambertSolution` | Transfer velocity vectors |
| `j2_secular_rates(a, e, i_deg, mu)` | `SecularRates` | RAAN and perigee precession rates |

## Example

```python
hoh = hohmann_delta_v(6778.0, 42164.0)
# HohmannResult(dv1_ms=2425, dv2_ms=1468, dv_total_ms=3893, tof_s=18924)
```

## Honest caveats

All computations assume a two-body central force model. J2 is a first-order perturbation; for high-fidelity mission design include higher harmonics, drag, SRP, and third-body forces via numerical integration. Lambert's solver may not converge for transfer angles near 0° or 180° (degenerate geometries). Bi-elliptic transfers are more efficient than Hohmann for r2/r1 > 11.94 but have much longer transfer times.

## References

- Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed. (2013), Ch. 5–6.
- Bate, Mueller & White, *Fundamentals of Astrodynamics*, Dover (1971).
