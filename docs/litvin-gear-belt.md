# Gear Mesh and Belt Drive Dynamics

> Compute tooth-contact forces, gear-mesh stiffness, and belt-drive tensions for MBD simulation.

**Module**: `packages/kerf-mates/src/kerf_mates/mbd/machinery.py`
**Shipped**: Wave 9C3
**LLM tools**: `gear_mesh_force`, `belt_drive_force`

---

## What it is

The machinery module models gear meshes as spring-damper elements along the tooth line of action (Litvin & Fuentes, 2004) and belt drives as catenary tension members with Euler-Eytelwein belt slip. `GearMeshDynamics` tracks tooth-mesh deformation and force over time; `BeltDrive` computes tight-side and slack-side tensions for flat and V-belts. Both are designed as force elements in a broader MBD model.

## How to use it

### From chat

> "Compute the tooth-contact force for a 3 kW motor gear pair at 1500 RPM, module 2, 20 teeth."

### From Python

```python
from kerf_mates.mbd.machinery import (
    GearMeshDynamics, gear_mesh_force, iso6336_tangential_force,
    BeltDrive, belt_drive_force,
)

gmd = GearMeshDynamics(
    module_mm=2.0,
    n_teeth_1=20, n_teeth_2=40,
    mesh_stiffness_n_per_m=2e8,
    backlash_mm=0.05,
)
F_tooth = gear_mesh_force(gmd, torque_nm=19.1, omega_rpm=1500)
print(F_tooth["tangential_n"], F_tooth["normal_n"])

bd = BeltDrive(
    pitch_diameter_1_mm=100, pitch_diameter_2_mm=200,
    centre_distance_mm=350, belt_type="v_belt",
    friction_coeff=0.35,
)
tensions = belt_drive_force(bd, torque_nm=50.0)
print(tensions["tight_side_n"], tensions["slack_side_n"])
```

### From an LLM tool spec

```json
{"tool": "gear_mesh_force", "input": {"module_mm": 2.0, "n_teeth_1": 20, "n_teeth_2": 40, "torque_nm": 19.1, "omega_rpm": 1500}}
```

## How it works

**Gear mesh**: The tangential force at the pitch point is `F_t = 2T / d_pitch`. The line-of-action normal force is `F_n = F_t / cos(pressure_angle)`. Dynamic tooth-mesh force includes a spring-damper term: `F_mesh = k_m × δ + c × δ̇`, where `δ` is the loaded tooth deflection and `k_m` is the mean mesh stiffness (Litvin §8). ISO 6336-1 load factors (KA, KV, KHβ) are applied for sizing.

**Belt**: Tight-side tension from Euler-Eytelwein: `T_tight = T_slack × e^(μθ)`, where `θ` is the wrap angle. The difference `T_tight − T_slack` delivers the transmitted torque.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `gear_mesh_force(gmd, torque_nm, omega_rpm)` | `dict` | Tangential, radial, normal tooth forces |
| `iso6336_tangential_force(gmd, power_kw, omega_rpm)` | `float` | ISO 6336 nominal tangential force |
| `belt_drive_force(bd, torque_nm)` | `dict` | Tight/slack side tensions |
| `chain_drive_tension(cd, torque_nm, omega_rpm)` | `dict` | Chain tight/slack tensions |

## Example

```python
F = gear_mesh_force(gmd, torque_nm=19.1, omega_rpm=1500)
# {'tangential_n': 191.0, 'radial_n': 69.6, 'normal_n': 203.4}
```

## Honest caveats

The gear-mesh model uses a constant mean stiffness; actual stiffness varies over the meshing cycle (contact ratio, single vs. double pair contact). Transmission error and noise prediction require a varying-mesh-stiffness model. Belt slip is estimated via Euler-Eytelwein; creep effects in elastomer belts are not modelled. Chain polygon action and roller impact are not included.

## References

- Litvin, F.L. & Fuentes, A., *Gear Geometry and Applied Theory*, 2nd ed., Cambridge (2004), §8.
- ISO 6336-1:2019, *Calculation of load capacity of spur and helical gears — Part 1: Basic principles*.
