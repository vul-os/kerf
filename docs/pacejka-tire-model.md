# Pacejka Magic Formula Tire Model

> Compute lateral and longitudinal tyre forces using the Pacejka Magic Formula for vehicle dynamics.

**Module**: `packages/kerf-mates/src/kerf_mates/mbd/vehicle_dynamics.py`
**Shipped**: Wave 9C3
**LLM tools**: `step_vehicle_dynamics`, `steady_state_cornering`

---

## What it is

The Pacejka Magic Formula (MF) tire model computes lateral force (from slip angle) and longitudinal force (from slip ratio) for vehicle dynamics simulation. It is integrated into a single-track bicycle vehicle model with weight transfer, and into a steady-state cornering solver. Based on Pacejka (2012), 3rd edition.

## How to use it

### From chat

> "Compute the lateral force on a front tyre at 5° slip angle, 4500 N normal load."

### From Python

```python
from kerf_mates.mbd.vehicle_dynamics import TireModel, step_vehicle, steady_state_cornering

tire = TireModel(
    By=8.0, Cy=1.3, Dy=1.0, Ey=-0.5,  # lateral MF coefficients
    Bx=10.0, Cx=1.9, Dx=1.0, Ex=0.97, # longitudinal MF coefficients
)
Fy = tire.lateral_force(slip_angle_rad=0.0873, normal_load_n=4500)
print(f"Lateral force: {Fy:.1f} N")

# Steady-state cornering radius
result = steady_state_cornering(spec=vehicle_spec, speed_ms=20.0)
print(result["turning_radius_m"], result["understeer_gradient"])
```

### From an LLM tool spec

```json
{"tool": "steady_state_cornering", "input": {"vehicle_spec": {...}, "speed_ms": 20.0}}
```

## How it works

The Magic Formula: `F = D sin(C arctan(B x − E(B x − arctan(B x))))` where `x` is slip angle (lateral) or slip ratio (longitudinal), and `B, C, D, E` are the stiffness, shape, peak, and curvature factors. The single-track vehicle step integrates the equations of motion for lateral velocity, yaw rate, and longitudinal velocity over a time step using Euler integration. Weight transfer is computed from lateral acceleration.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `TireModel.lateral_force(slip_angle_rad, normal_load_n)` | `float` | Lateral tyre force (N) |
| `TireModel.longitudinal_force(slip_ratio, normal_load_n)` | `float` | Longitudinal tyre force (N) |
| `step_vehicle(spec, state, dt, steering_rad, throttle)` | `VehicleState` | One MBD time step |
| `steady_state_cornering(spec, speed_ms)` | `dict` | Cornering radius and understeer gradient |

## Example

```python
Fy = tire.lateral_force(0.0873, 4500)  # 5° slip angle
# 3241.7 N
Fx = tire.longitudinal_force(0.05, 4500)  # 5% slip ratio
# 1872.3 N
```

## Honest caveats

The simplified Magic Formula omits combined-slip (simultaneous lateral + longitudinal slip) interaction; use the full TNO MF-Tyre model for combined manoeuvres. The vehicle model is a single-track (bicycle) model: it ignores roll dynamics, suspension kinematics, and chassis flexibility. MF coefficients (B, C, D, E) must be calibrated from tyre test data; default values are generic passenger-car estimates.

## References

- Pacejka, H.B., *Tire and Vehicle Dynamics*, 3rd ed., Elsevier (2012), Ch. 4.
- Rajamani, R., *Vehicle Dynamics and Control*, 2nd ed., Springer (2012), Ch. 2.
