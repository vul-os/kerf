# Orbital Mechanics

*Domain: Aerospace · Module: `packages/kerf-aero/src/kerf_aero/llm_tools/aerospace_tools.py` · Shipped: Wave 9*

## Overview

Two-body orbital mechanics: conversion between orbital elements and Cartesian state vectors, Hohmann transfer delta-V, Lambert's problem solver (two-point boundary-value problem for determining transfer orbits), and J2 perturbation propagator. Covers both circular and elliptical orbits around Earth and other central bodies.

## When to use

- Computing the delta-V budget for a Hohmann transfer between circular orbits.
- Converting orbital elements (a, e, i, Ω, ω, M) to/from position-velocity vectors.
- Solving Lambert's problem for rendezvous or interplanetary trajectory design.
- Estimating RAAN drift rate due to J2 oblateness perturbation.

## API

```python
# Via LLM tools — orchestrated through the aerospace_tools ToolSpec
# Direct Python:
from kerf_aero.llm_tools.aerospace_tools import handle_aerospace_tool

result = handle_aerospace_tool("aero_orbital_elements_to_state", {
    "a_km": 6778.0,
    "e": 0.001,
    "i_deg": 28.5,
    "raan_deg": 45.0,
    "argp_deg": 0.0,
    "true_anomaly_deg": 0.0,
})

hohmann = handle_aerospace_tool("aero_hohmann_transfer", {
    "r1_km": 6778.0,
    "r2_km": 42164.0,
    "mu_km3s2": 398600.4418,
})
print(hohmann["delta_v1_ms"], hohmann["delta_v2_ms"])
```

## LLM tools

`aero_orbital_elements_to_state`, `aero_hohmann_transfer`, `aero_lambert_solve`

## References

- Vallado, *Fundamentals of Astrodynamics and Applications*, 4th ed. (2013).
- Bate, Mueller & White, *Fundamentals of Astrodynamics* (1971).
- Lancaster & Blanchard, "A unified form of Lambert's theorem", *NASA TN D-5368*, 1969.

## Honest caveats

All computations assume a two-body central force model. J2 is a first-order perturbation; higher-order zonal harmonics, solar radiation pressure, atmospheric drag, and lunar/solar third-body effects are not modelled. Lambert's solver uses the universal variable formulation and may not converge for transfer angles very close to 0° or 180°.
