# Rocket Propulsion and Tsiolkovsky Delta-V

> Compute Tsiolkovsky delta-V, Isp from propellant chemistry, staging optimisation, and thrust from mass flow.

**Module**: `packages/kerf-aero/src/kerf_aero/propulsion/rocket_eq.py`
**Shipped**: Wave 9
**LLM tools**: `aero_rocket_dv`, `aero_cea_lite`

---

## What it is

Rocket propulsion fundamentals: Tsiolkovsky rocket equation (delta-V from mass ratio and Isp), thrust from mass flow and effective exhaust velocity, multi-stage optimisation by Lagrange multiplier staging, and CEA-lite frozen-flow chemical equilibrium for propellant performance estimation.

## How to use it

### From chat

> "Size a LOX/RP-1 upper stage for 3 km/s delta-V with a 2000 kg dry mass."

### From Python

```python
from kerf_aero.propulsion.rocket_eq import (
    delta_v, propellant_mass, mass_ratio_for_delta_v,
    isp_from_cstar, thrust_from_mass_flow,
)

# Tsiolkovsky delta-V for a 3-stage vehicle
dv = delta_v(isp=311.0, m0=10000, mf=4000)
print(dv["delta_v_ms"])

# Required propellant for 3 km/s burn
pm = propellant_mass(isp=311.0, m_dry=2000, delta_v_ms=3000)
print(pm["propellant_kg"], pm["m0_kg"])

# Isp from c* and expansion ratio
isp = isp_from_cstar(c_star=1760, gamma=1.22, p_c=50e5, p_e=0.01e5, Ae_At=30)
```

### From an LLM tool spec

```json
{"tool": "aero_rocket_dv", "input": {"isp": 311, "m0": 10000, "mf": 4000}}
```

## How it works

Tsiolkovsky: `Δv = Isp × g₀ × ln(m₀/mf)`. Multi-stage optimal split: Lagrange multiplier method minimises total initial mass subject to total delta-V constraint — each stage has the same structural fraction `ε = m_struct / (m_struct + m_prop)`. CEA-lite: curve-fit polynomial approximations to NASA CEA2 equilibrium results for common propellant combinations (LOX/LH2, LOX/RP-1, N2O/HTPB) over mixture-ratio and chamber-pressure ranges.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `delta_v(isp, m0, mf)` | `dict` | Tsiolkovsky delta-V |
| `propellant_mass(isp, m_dry, delta_v_ms)` | `dict` | Required propellant mass |
| `mass_ratio_for_delta_v(delta_v_ms, isp)` | `dict` | Mass ratio m0/mf |
| `isp_from_cstar(c_star, gamma, p_c, p_e, Ae_At)` | `dict` | Theoretical Isp from nozzle parameters |
| `thrust_from_mass_flow(m_dot, isp)` | `dict` | Thrust from mass flow rate |

## Example

```python
pm = propellant_mass(isp=311.0, m_dry=2000, delta_v_ms=3000)
# {'propellant_kg': 3841, 'm0_kg': 5841, 'mass_ratio': 2.92}
```

## Honest caveats

CEA-lite covers frozen-flow equilibrium only; shifting equilibrium gives ~1–3% higher Isp for some propellants. Real nozzle losses (divergence, two-phase, boundary layer) reduce delivered Isp by 3–8%; apply an efficiency factor η ≈ 0.93. Gravity and drag losses during ascent must be estimated separately. The Lagrange-multiplier staging optimisation assumes identical structural fractions for all stages.

## References

- Tsiolkovsky, "Exploration of the World Space with Reaction Machines," *Nauchnoye Obozreniye* 5, 1903.
- Sutton & Biblarz, *Rocket Propulsion Elements*, 9th ed. (2017), Ch. 3.
- McBride & Gordon, *NASA CEA2*, NASA RP-1311 (1996).
