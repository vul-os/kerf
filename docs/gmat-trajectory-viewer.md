# GMAT-Style Trajectory Viewer

> Visualise and export multi-body spacecraft trajectories in a GMAT-compatible 3-D viewer format.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/aerospace/aerospace_tools.py`
**Shipped**: Wave 10C2
**LLM tools**: `aerospace_compute_lagrange_points`, `aerospace_design_halo_orbit`

---

## What it is

The GMAT-style trajectory viewer takes a propagated state history (time series of ECI position/velocity) and renders it as an interactive 3-D orbit visualisation or exports it in GMAT script format for import into NASA's General Mission Analysis Tool. It supports multi-segment trajectories (launch, transfer, insertion, station-keeping) and overlays the primary and secondary body positions.

## How to use it

### From chat

> "Export my Halo orbit trajectory as a GMAT script for the Earth-Moon L2 point."

### From Python

```python
from kerf_cad_core.aerospace.libration_orbits import design_halo_orbit, CR3BPSystem
from kerf_cad_core.aerospace.aerospace_tools import export_trajectory_gmat

system = CR3BPSystem(
    m1=5.974e24, m2=7.342e22, L=384400e3, name="Earth-Moon"
)
halo = design_halo_orbit(system, "L2", z_amplitude_km=8000, family="northern")

gmat_script = export_trajectory_gmat(
    state_history=halo.state_history,
    epoch_iso="2025-07-01T00:00:00Z",
    body_name="Moon",
    spacecraft_name="LunarGateway",
)
with open("halo_l2.script", "w") as f:
    f.write(gmat_script)
```

### From an LLM tool spec

```json
{"tool": "aerospace_design_halo_orbit", "input": {"system": "Earth-Moon", "libration_point": "L2", "z_amplitude_km": 8000}}
```

## How it works

`export_trajectory_gmat` writes a GMAT script that: (1) defines the spacecraft initial state in the Moon-centred inertial frame; (2) configures a Propagator (Runge-Kutta 8-9) with the PointMassForce model; (3) sets up an EphemerisFile subscriber to log the trajectory; (4) adds a OrbitView 3-D display targeting the L2 libration point. The synodic-frame CR3BP state history is converted to ECI by rotating by the current Moon angle.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `export_trajectory_gmat(state_history, epoch_iso, body_name, spacecraft_name)` | `str` | GMAT script text |

## Example

```python
script = export_trajectory_gmat(halo.state_history, "2025-07-01T00:00:00Z", "Moon", "LunarGateway")
# Returns multi-line GMAT script string
# Save and open in GMAT 2024a for interactive 3-D visualisation
```

## Honest caveats

The GMAT script exports use GMAT's internal Moon-centred inertial frame, which requires the GMAT SPICE kernels (de430.bsp) to be installed. The CR3BP synodic-to-ECI rotation uses a constant Moon angular velocity (circular orbit assumption); for high-fidelity work, use the full ephemeris Moon angle from SPICE. The viewer export is not a full GMAT mission sequence — manoeuvres, thrusters, and sensors must be added manually in GMAT.

## References

- NASA GSFC, *GMAT R2022a User Guide*, 2022. gmat.gsfc.nasa.gov.
- Betts, *Practical Methods for Optimal Control Using Nonlinear Programming*, 2nd ed. (2010).
