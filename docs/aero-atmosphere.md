# Atmosphere Models and Flight Performance

*Domain: Aerospace · Module: `packages/kerf-aero/src/kerf_aero/flight_dynamics/atmosphere.py` · Shipped: Wave 9*

## Overview

Standard atmosphere models (ISA 1976, US Standard Atmosphere) with temperature, pressure, density, speed of sound, and dynamic viscosity as functions of geometric or geopotential altitude. Includes the ISA non-standard day extension (temperature offset ΔT). Used for performance calculations, propulsion sizing, and Reynolds number estimation.

## When to use

- Computing density altitude for take-off performance calculations.
- Obtaining air properties at cruise altitude for drag and propulsion analysis.
- Applying ISA +20°C or ISA -20°C non-standard conditions for performance margins.

## API

```python
from kerf_aero.flight_dynamics.atmosphere import (
    isa_atmosphere,
    density_altitude,
    speed_of_sound,
)

# ISA standard day at 10,000m geometric altitude
atm = isa_atmosphere(h_m=10000.0, dT_isa=0.0)
print(atm["T_K"], atm["p_Pa"], atm["rho_kg_m3"])
print(atm["a_ms"])     # speed of sound
print(atm["mu_Pa_s"])  # dynamic viscosity

# ISA+20°C hot day
atm_hot = isa_atmosphere(h_m=0.0, dT_isa=20.0)

# Density altitude from field elevation and OAT
da = density_altitude(pressure_alt_m=500, OAT_C=35.0)
```

## LLM tools

`aero_atmosphere`

## References

- ICAO Doc 7488, *Manual of the ICAO Standard Atmosphere* (1993, 3rd ed.).
- NASA TM-X-74335, *US Standard Atmosphere, 1976*.

## Honest caveats

The ISA model uses constant lapse rates per standard layer and does not model atmospheric turbulence, humidity effects on density, or wind profiles. Molecular viscosity uses Sutherland's formula. Above 86 km the atmosphere departs significantly from the hydrostatic model; results above 85 km are extrapolated.
