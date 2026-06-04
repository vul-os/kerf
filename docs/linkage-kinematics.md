# Linkage and Cam Kinematics

*Domain: Mechanical · Module: `packages/kerf-cad-core/src/kerf_cad_core/kinematics/linkage.py` · Shipped: Wave 8*

## Overview

Planar mechanism analysis for four-bar linkages and slider-cranks: Grashof classification, position analysis (all coupler-link positions for a given crank rotation), transmission angle, coupler-curve generation, and cam follower motion synthesis (cycloidal and harmonic displacement programs). Used for mechanism design, motion timing charts, and machine element sizing.

## When to use

- Checking if a four-bar linkage satisfies Grashof's condition for full rotation.
- Computing the coupler-curve for a mechanism synthesis study.
- Designing a cycloidal cam for a given rise/dwell/fall motion profile.
- Checking transmission angles to ensure force transmission quality.

## API

```python
from kerf_cad_core.kinematics.linkage import (
    four_bar_grashof,
    four_bar_position,
    four_bar_coupler_curve,
    four_bar_transmission_angle,
    slider_crank,
    cam_follower_cycloidal,
    cam_follower_harmonic,
)

grashof = four_bar_grashof(l1=50, l2=30, l3=40, l4=35)
print(grashof["class"], grashof["satisfies_grashof"])

positions = four_bar_position(
    l1=50, l2=30, l3=40, l4=35,
    theta2_deg=45.0,
)

cam = cam_follower_cycloidal(
    beta_rise_deg=90,   # cam angle for rise
    h=20.0,             # lift in mm
    n_pts=180,
)
```

## LLM tools

`feature_linkage_kinematic`, `feature_cam_follower`

## References

- Shigley & Uicker, *Theory of Machines and Mechanisms*, 5th ed. (2016).
- Norton, *Design of Machinery*, 5th ed. (2011).

## Honest caveats

Position analysis uses the Freudenstein equation for the four-bar; assembly-mode selection (open vs. crossed) is determined by the sign of the discriminant. Velocity and acceleration analysis requires numerical differentiation of position results — not provided directly. Coupler-curve generation is for the moving pivot on the coupler; arbitrary coupler-point paths require specifying the coupler-point attachment explicitly.
