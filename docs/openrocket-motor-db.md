# Rocket Motor Database (OpenRocket / RASP format)

> Look up, parse, and simulate solid rocket motors from built-in Estes/AeroTech catalogs or RASP .eng files.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/aerospace/motor_database.py`
**Shipped**: Wave 10C2
**LLM tools**: `aero_rocket_dv`

---

## What it is

The motor database stores parametric solid rocket motor records (designation, diameter, length, propellant mass, thrust curve) in the RASP `.eng` format — the standard exchange format used by OpenRocket, RASAero, and Thrustcurve.org. Built-in catalogs cover common Estes (A through G) and AeroTech (E through N) hobby and high-power motors. The `compute_burnout_velocity` function integrates the thrust curve to give flight velocity at burnout.

## How to use it

### From chat

> "What is the burnout velocity for a 500 g rocket (dry mass 200 g) on an AeroTech J500G motor?"

### From Python

```python
from kerf_cad_core.aerospace.motor_database import (
    estes_motor_catalog, aerotech_motor_catalog,
    parse_rasp_eng_file, compute_burnout_velocity,
)

# Built-in catalog lookup
motors = aerotech_motor_catalog()
j500 = next(m for m in motors if "J500G" in m.designation)

print(j500.total_impulse_ns, j500.avg_thrust_n, j500.burn_time_s)

# Burnout velocity
result = compute_burnout_velocity(
    motor=j500,
    m_dry_kg=0.200,    # rocket dry mass
    drag_coefficient=0.4,
    ref_area_m2=0.002,
    launch_angle_deg=85.0,
)
print(result["burnout_velocity_ms"], result["max_altitude_m"])
```

### From an LLM tool spec

```json
{"tool": "aero_rocket_dv", "input": {"isp": 195, "m0": 0.500, "mf": 0.200}}
```

## How it works

RASP `.eng` files list time-thrust pairs; `parse_rasp_eng_file` reads the header (designation, diameter, length, propellant mass, total mass, manufacturer) and the thrust-time curve. Total impulse is computed by trapezoidal integration of the thrust curve. `compute_burnout_velocity` integrates the 1-D equation of motion `m(t) ẍ = T(t) − D(v) − m g sin(θ)` using Euler steps over the burn duration, with mass decreasing as `ṁ = T / (g₀ Isp)`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `estes_motor_catalog()` | `list[RocketMotor]` | Built-in Estes motor records |
| `aerotech_motor_catalog()` | `list[RocketMotor]` | Built-in AeroTech motor records |
| `parse_rasp_eng_file(content)` | `list[RocketMotor]` | Parse RASP .eng file |
| `compute_burnout_velocity(motor, m_dry_kg, Cd, A, angle_deg)` | `dict` | Burnout velocity and altitude |

## Example

```python
motors = estes_motor_catalog()
c6 = next(m for m in motors if m.designation == "C6-5")
print(c6.total_impulse_ns)   # 8.82 N·s
res = compute_burnout_velocity(c6, m_dry_kg=0.08)
# {'burnout_velocity_ms': 38.4, 'max_altitude_m': 110.2}
```

## Honest caveats

Thrust curves in the built-in catalogs are nominal; production motors have lot-to-lot variation of ±5–10% in total impulse. The burnout velocity calculation is 1-D (no wind, no pitch-over) — it is valid for nearly vertical flight near launch only. Aerodynamic drag coefficient must be supplied; the default (0.4) is approximate for a typical cylindrical rocket body. Propellant regression, combustion stability, and temperature sensitivity are not modelled.

## References

- Cyr, S., *RASP Engine Data Format*, NAR (1997). Thrustcurve.org (2024).
- Sutton & Biblarz, *Rocket Propulsion Elements*, 9th ed. (2017), Ch. 2.
