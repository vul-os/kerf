# Gravity Pipe Network (Manning / Hydraulics)

*Domain: Civil · Module: `packages/kerf-civil/src/kerf_civil/hydraulics_gravity.py` · Shipped: Wave 10*

## Overview

Computes normal depth, full-flow capacity, and flow at partial depth for circular pipes and trapezoidal open channels using Manning's equation. Supports the standard hydraulic geometry relations (hydraulic radius, wetted perimeter, area). Used for stormwater drainage design and sanitary sewer sizing per ASCE gravity pipe design standards.

## When to use

- Sizing a circular storm drain for a given peak discharge.
- Computing normal depth for a partially full pipe at a given flow.
- Designing open channels (roadside swales, ditches) for uniform flow.

## API

```python
from kerf_civil.hydraulics_gravity import (
    circular_section_geometry,
    circular_full_flow,
    circular_capacity_at_depth,
    circular_normal_depth,
    trapezoidal_geometry,
    trapezoidal_capacity,
    trapezoidal_normal_depth,
)

# 600mm diameter pipe, n=0.013, slope=0.005
Q_full = circular_full_flow(d=0.600, n=0.013, slope=0.005)

# Normal depth for Q=0.05 m³/s in the same pipe
yn = circular_normal_depth(Q=0.05, d=0.600, n=0.013, slope=0.005)

# Trapezoidal channel: 1.0m base, 2:1 side slopes
Q_trap = trapezoidal_capacity(b=1.0, z=2.0, n=0.025, slope=0.002, y=0.8)
```

## LLM tools

`civil_gravity_pipe_size`, `civil_open_channel`

## References

- Manning, "On the flow of water in open channels and pipes", *Trans. ICE Ireland* 20, 1891.
- ASCE/WEF MOP No. 36, *Design of Urban Stormwater Controls* (2012).

## Honest caveats

Manning's equation applies to uniform, steady-state flow only. Energy and hydraulic grade line profiles (gradually-varied flow) are not computed by this module. For pressure-grade calculations use `hydraulics_pressure.py`. The normal-depth solver uses bisection and may require up to 50 iterations for convergence to 0.1mm.
