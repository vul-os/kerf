# Atmosphere Models (ISA 1976)

> Compute temperature, pressure, density, speed of sound, and viscosity at any altitude with optional ISA ΔT offset.

**Module**: `packages/kerf-aero/src/kerf_aero/flight_dynamics/atmosphere.py`
**Shipped**: Wave 9
**LLM tools**: `aero_atmosphere`

---

## What it is

Standard atmosphere models (ISA 1976, US Standard Atmosphere) with temperature, pressure, density, speed of sound, and dynamic viscosity as functions of geometric or geopotential altitude. Includes the ISA non-standard day extension (temperature offset ΔT). Used for performance calculations, propulsion sizing, and Reynolds number estimation.

## How to use it

### From chat

> "What is the air density at 10,000 m on an ISA +20°C hot day?"

### From Python

```python
from kerf_aero.flight_dynamics.atmosphere import (
    atmosphere, mach_number, dynamic_pressure,
)

# ISA standard day at 10,000 m geometric altitude
atm = atmosphere(altitude_m=10000.0, geometric=True)
print(atm.T_K, atm.p_Pa, atm.rho_kg_m3)
print(atm.a_ms)      # speed of sound
print(atm.mu_Pa_s)   # dynamic viscosity

# Mach number at 250 m/s TAS, 10,000 m
M = mach_number(true_airspeed_m_s=250.0, altitude_m=10000.0)

# Dynamic pressure at 250 m/s, 10,000 m
q = dynamic_pressure(true_airspeed_m_s=250.0, altitude_m=10000.0)
```

### From an LLM tool spec

```json
{"tool": "aero_atmosphere", "input": {"altitude_km": 10.0}}
```

## How it works

The ISA model uses seven standard layers with constant temperature lapse rates (6.5 K/km in the troposphere, 0 in the lower stratosphere, etc.). Pressure is derived from the hydrostatic equation; density from the ideal gas law. Speed of sound: `a = √(γ R T)`. Molecular viscosity uses Sutherland's formula: `μ = μ_ref (T/T_ref)^(3/2) (T_ref + S)/(T + S)`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `atmosphere(altitude_m, geometric)` | `AtmosphereState` | Full ISA state at altitude |
| `mach_number(TAS_m_s, altitude_m)` | `float` | Mach number |
| `dynamic_pressure(TAS_m_s, altitude_m)` | `float` | Dynamic pressure (Pa) |
| `geometric_to_geopotential(h_geom_m)` | `float` | Altitude conversion |

## Example

```python
atm = atmosphere(10000.0)
# AtmosphereState(T_K=223.3, p_Pa=26500, rho_kg_m3=0.414, a_ms=299.5)
```

## Honest caveats

The ISA model uses constant lapse rates per standard layer and does not model atmospheric turbulence, humidity effects on density, or wind profiles. Above 86 km the atmosphere departs significantly from the hydrostatic model; results above 85 km are extrapolated and should not be used for hypersonic design.

## References

- ICAO Doc 7488, *Manual of the ICAO Standard Atmosphere*, 3rd ed. (1993).
- NASA TM-X-74335, *US Standard Atmosphere, 1976*.
