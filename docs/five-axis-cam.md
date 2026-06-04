# Five-Axis CNC Kinematics

*Domain: CAM · Module: `packages/kerf-cad-core/src/kerf_cad_core/fiveaxis/kinematics.py` · Shipped: Wave 9*

## Overview

Forward kinematics for common 5-axis CNC machine configurations (BC, AC, AB table-table, and head-table variants). Transforms tool-axis vectors and CL (cutter location) points into joint-space machine coordinates, handling rotary-axis wrapping, singularity-aware interpolation, and RTCP (Rotary Tool Centre Point) compensation. Used to verify machine-specific toolpath output before NC posting.

## When to use

- Converting a tool-axis vector CLF file into machine-joint rotary angles for a specific 5-axis machine.
- Checking for A/C axis wraparound or singularity passages in a toolpath.
- Validating RTCP compensation parameters against a machine's geometry.

## API

```python
from kerf_cad_core.fiveaxis.kinematics import (
    MachineConfig, MachineType, RotaryAxis,
    forward_kinematics,
)

machine = MachineConfig(
    machine_type=MachineType.BC_TABLE_TABLE,
    rotary_b=RotaryAxis(offset=[0, 0, 100], axis=[0, 1, 0]),
    rotary_c=RotaryAxis(offset=[0, 0, 0],   axis=[0, 0, 1]),
)

# Tool axis vector and CL point
result = forward_kinematics(
    machine=machine,
    tool_axis=[0.0, 0.707, 0.707],   # 45° from vertical
    cl_point=[50.0, 30.0, 10.0],
)
print(result["B_deg"], result["C_deg"])   # machine joint angles
print(result["machine_pos"])              # XYZ machine position
```

## LLM tools

`cam_5axis_kinematics`, `cam_5axis_toolpath_verify`

## References

- Erkorkmaz & Altintas, "High speed CNC system design: Part I — jerk limited trajectory generation", *IJMT* 41(9), 2001.
- Bohez et al., "The characteristic and optimal design of the five-axis milling machine", *Annals of the CIRP* 42(1), 1993.

## Honest caveats

Forward kinematics is implemented for the four most common 5-axis configurations. Machine-specific geometric errors (squareness, parallelism, scale errors) are not modelled. For positional accuracy > 10 μm, use the machine's ballbar calibration data to correct the kinematic model. Singularity detection reports when the rotary axis alignment is within 1° of a singular configuration.
