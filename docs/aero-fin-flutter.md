# Fin Flutter and Aeroelasticity

> Compute fin flutter speed, flutter frequency, and Barrowman stability margin for rocket and UAV fins.

**Module**: `packages/kerf-aero/src/kerf_aero/fin_flutter.py`
**Shipped**: Wave 9
**LLM tools**: `aero_fin_flutter`, `aero_flutter_pk`

---

## What it is

Structural flutter analysis for rocket fins using the Theodorsen strip-theory flutter equation and the p-k flutter solver for general wing/fin configurations. Computes flutter speed (V_F), flutter frequency (ω_F), and flutter margin. Also includes Barrowman centre-of-pressure calculation for static stability checking.

## How to use it

### From chat

> "Check if my 150 mm semi-span aluminium fin is flutter-free at max-Q (Mach 0.8, 3 km altitude)."

### From Python

```python
from kerf_aero.fin_flutter import fin_flutter_speed, barrowman_cp

result = fin_flutter_speed(
    semi_span_m=0.15,
    root_chord_m=0.12,
    tip_chord_m=0.06,
    sweep_deg=30.0,
    thickness_fraction=0.06,
    rho_kg_m3=2700,    # aluminium
    E_Pa=69e9, G_Pa=26e9,
    air_density=0.91,   # kg/m³ at 3 km
    speed_of_sound=328.0,  # m/s at 3 km
)
print(result.V_flutter_ms, result.flutter_margin_fraction)

cp = barrowman_cp(nose_length_m=0.3, body_diameter_m=0.076,
                   fin_span_m=0.30, fin_root_chord_m=0.12,
                   fin_tip_chord_m=0.06, sweep_deg=30.0)
print(cp["X_cp_m"])
```

### From an LLM tool spec

```json
{"tool": "aero_fin_flutter", "input": {"semi_span_m": 0.15, "root_chord_m": 0.12, "thickness_fraction": 0.06, "E_Pa": 69e9, "altitude_m": 3000}}
```

## How it works

Theodorsen strip theory models each spanwise strip as a 2-D unsteady flat-plate aerofoil. The flutter condition is an eigenvalue problem in the structural (bending, torsion) and aerodynamic (lift, moment) modes. The flutter speed is the airspeed at which the imaginary part of a root crosses zero (onset of oscillatory instability). Barrowman's equations give the normal-force coefficient slopes for nose, body, and fins, combined to locate the centre of pressure.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `fin_flutter_speed(...)` | `FinFlutterResult` | Flutter speed and margin |
| `barrowman_cp(...)` | `RocketStabilityResult` | Centre of pressure location |

## Example

```python
r = fin_flutter_speed(0.15, 0.12, 0.06, 30.0, 0.06, 2700, 69e9, 26e9, 0.91, 328.0)
# FinFlutterResult(V_flutter_ms=423, flutter_margin_fraction=0.41, flutter_freq_hz=18.3)
```

## Honest caveats

Theodorsen strip theory assumes 2-D unsteady aerodynamics per span strip; 3-D tip relief typically raises flutter speed by 10–20% for low-aspect-ratio fins. The single-mode (bending or torsion) approximation may miss coupled bending-torsion flutter; use the p-k solver for that. The transonic flutter dip (Mach 0.85–1.1) is not captured by the subsonic aerodynamic model.

## References

- Theodorsen, "General theory of aerodynamic instability and the mechanism of flutter," *NACA TR 496*, 1935.
- Barrowman, *The Theoretical Prediction of the Centre of Pressure*, MIT (1967).
