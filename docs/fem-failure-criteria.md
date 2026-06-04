# Composite Failure Criteria

> Evaluate Tsai-Wu, Tsai-Hill, Hashin, Puck, and maximum stress/strain failure criteria for fibre-composite laminates — predict first-ply failure and failure index maps.

**Module**: `packages/kerf-fem/src/kerf_fem/composites/failure_criteria.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run` (analysis `"composite_failure"`)

---

## What it is

Composite laminates fail by multiple mechanisms: fibre tension/compression, matrix tension/compression, and fibre-matrix shear. Each failure criterion defines a scalar failure index (FI): FI < 1.0 is safe; FI ≥ 1.0 means failure. Different criteria have different fidelity: Tsai-Wu is a smooth polynomial fit; Hashin separates fibre and matrix modes; Puck's action-plane criterion is the most physically accurate for unidirectional composites.

This module evaluates five criteria on any ply stress state (in material coordinates σ₁, σ₂, τ₁₂) and performs first-ply failure analysis on a full laminate, identifying which ply fails first and at what load level.

## How to use it

### From chat (natural language)

> "Check all failure criteria for a [0/90/±45]_s CFRP laminate under 1000 N/m in-plane load"

The LLM calls `fem_run` with analysis `"composite_failure"`.

### From Python

```python
from kerf_fem.composites.failure_criteria import (
    tsai_wu, tsai_hill, hashin, puck, maximum_stress,
    first_ply_failure_analysis, FailureResult,
)

# Ply strengths (Pa)
strengths = dict(
    Xt=1500e6, Xc=1200e6,  # fibre tension, compression
    Yt=50e6,  Yc=200e6,    # matrix tension, compression
    S12=80e6,               # in-plane shear
)
sigma_ply = (300e6, 20e6, 15e6)  # σ1, σ2, τ12

tw  = tsai_wu(sigma_ply, **strengths)
has = hashin(sigma_ply, **strengths)
pk  = puck(sigma_ply, **strengths)
print(f"Tsai-Wu FI:  {tw.failure_index:.3f} ({tw.mode})")
print(f"Hashin FI:   {has.failure_index:.3f} ({has.mode})")
print(f"Puck FI:     {pk.failure_index:.3f} ({pk.mode})")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "composite_failure",
 "sigma_1_MPa": 300, "sigma_2_MPa": 20, "tau_12_MPa": 15,
 "Xt_MPa": 1500, "Xc_MPa": 1200, "Yt_MPa": 50, "Yc_MPa": 200, "S12_MPa": 80}}
```

## How it works

**Tsai-Wu**: f₁σ₁ + f₂σ₂ + f₁₁σ₁² + f₂₂σ₂² + f₆₆τ₁₂² + 2f₁₂σ₁σ₂ ≤ 1, with interaction term f₁₂ = -√(f₁₁f₂₂)/2.

**Hashin**: separates fibre failure (σ₁/Xt)² + (τ₁₂/S)² ≤ 1 (tension) and matrix failure (σ₂/Yt)² + (τ₁₂/SL)² ≤ 1 (tension).

**Puck**: computes the action-plane angle θ by minimising the failure criterion over the fracture plane orientation — the most accurate predictor for matrix-dominated failure.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `tsai_wu(sigma_ply, Xt, Xc, Yt, Yc, S12)` | `FailureResult` | Tsai-Wu polynomial criterion |
| `tsai_hill(sigma_ply, Xt, Xc, Yt, S12)` | `FailureResult` | Tsai-Hill criterion |
| `maximum_stress(sigma_ply, Xt, Xc, Yt, Yc, S12)` | `FailureResult` | Max stress per component |
| `maximum_strain(eps_ply, eXt, eXc, eYt, eYc, eS12)` | `FailureResult` | Max strain criterion |
| `hashin(sigma_ply, Xt, Xc, Yt, Yc, S12)` | `FailureResult` | Hashin 2D fibre/matrix |
| `puck(sigma_ply, Xt, Xc, Yt, Yc, S12, p_ptp, p_pcp)` | `FailureResult` | Puck action-plane criterion |
| `first_ply_failure_analysis(laminate, loads, criteria)` | `dict` | First-ply failure load and ply |

`FailureResult` fields: `failure_index`, `mode` (`"fibre_tension"`, `"matrix_compression"`, etc.), `safe`.

## Example

```python
fpf = first_ply_failure_analysis(laminate, loads={"Nxx": 1000}, criteria=["hashin", "puck"])
print(f"First ply failure at Nxx = {fpf['failure_load_N_m']:.0f} N/m")
print(f"Failing ply: {fpf['failing_ply_index']}, mode: {fpf['mode']}")
```

## Honest caveats

First-ply failure is not ultimate failure — composites often carry significant load after first-ply failure through progressive damage. Tsai-Wu with f₁₂ = -0.5√(f₁₁f₂₂) gives conservative estimates; experimental f₁₂ determination is recommended for final design. Puck's criterion requires the inclination parameters p_ptp and p_pcp (typically 0.27 and 0.32 for CFRP) which are material-dependent.

## References

- Tsai & Wu (1971). "A general theory of strength for anisotropic materials." *J. Composite Materials* 5(1).
- Hashin (1980). "Failure criteria for unidirectional fiber composites." *J. Applied Mechanics* 47(2).
- Puck & Schürmann (1998). "Failure analysis of FRP laminates by means of physically based phenomenological models." *Composites Science and Technology* 58(7).
