# Rocket Propulsion and Tsiolkovsky Delta-V

*Domain: Aerospace · Module: `packages/kerf-aero/src/kerf_aero/propulsion/rocket_eq.py` · Shipped: Wave 9*

## Overview

Rocket propulsion fundamentals: Tsiolkovsky rocket equation (delta-V from mass ratio and Isp), thrust from mass flow and effective exhaust velocity, staging optimisation, and CEA-lite chemical equilibrium approximation for propellant performance. Covers single-stage and multi-stage vehicles with optional gravity and drag losses.

## When to use

- Preliminary sizing of a rocket stage for a given delta-V budget.
- Comparing propellant combinations (LOX/LH2, LOX/RP-1, N2O/HTPB) by Isp.
- Multi-stage mass ratio optimisation (Tsiolkovsky equation, Lagrange multiplier staging).

## API

```python
from kerf_aero.propulsion.rocket_eq import (
    delta_v, effective_exhaust_velocity,
    isp_from_cstar, thrust_from_mass_flow,
    mass_ratio_for_delta_v, propellant_mass,
)

# Tsiolkovsky delta-V
dv = delta_v(isp=311.0, m0=10000, mf=4000)
print(dv["delta_v_ms"])   # m/s

# Required propellant mass for a 3 km/s burn
pm = propellant_mass(isp=311.0, m_dry=4000, delta_v_ms=3000)
```

## LLM tools

`aero_rocket_dv`, `aero_cea_lite`

## References

- Tsiolkovsky, "Exploration of the World Space with Reaction Machines", *Nauchnoye Obozreniye* 5, 1903.
- Sutton & Biblarz, *Rocket Propulsion Elements*, 9th ed. (2017).
- McBride & Gordon, *CEA2* (NASA RP-1311, 1996).

## Honest caveats

The CEA-lite implementation covers frozen-flow equilibrium only; shifting-composition equilibrium and finite-rate chemistry are not modelled. Real nozzle losses (divergence, two-phase, boundary layer) are not included; apply an efficiency factor (η ≈ 0.92–0.97) to the theoretical Isp. Gravity and drag losses during ascent must be supplied externally.
