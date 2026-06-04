# Composite Failure Criteria (Tsai-Wu, Tsai-Hill, Hashin)

> Evaluate ply failure margins for fibre-composite laminates using five industry-standard criteria.

**Module**: `packages/kerf-fem/src/kerf_fem/composites/failure_criteria.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

The composite failure module evaluates five ply-level failure criteria — Tsai-Wu, Tsai-Hill, Maximum Stress, Maximum Strain, and Hashin — given the ply stress state and material strengths. `first_ply_failure_analysis` iterates over all plies in a laminate and returns the first ply to fail, the criterion, failure mode, and failure index (FI ≥ 1 = failure).

## How to use it

### From chat

> "Check Tsai-Wu failure for all plies in my [0/90/±45]_s laminate under biaxial loading."

### From Python

```python
from kerf_fem.composites.failure_criteria import (
    tsai_wu, tsai_hill, hashin, first_ply_failure_analysis,
)

strengths = {
    "Xt": 1500e6, "Xc": 1000e6,  # longitudinal tensile/compressive strength
    "Yt": 40e6,   "Yc": 200e6,   # transverse tensile/compressive strength
    "S12": 70e6,                   # shear strength
}
ply_stress = [800e6, 20e6, 30e6]  # σ₁, σ₂, τ₁₂

result = tsai_wu(ply_stress, strengths)
print(f"FI = {result.failure_index:.3f}, mode = {result.mode}")

lam_result = first_ply_failure_analysis(laminate, load_factor_range=(0, 2.0, 0.1))
print(lam_result.critical_load_factor, lam_result.first_failed_ply)
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "composite_failure", "criterion": "tsai_wu", "sigma1": 800e6, "sigma2": 20e6, "tau12": 30e6}}
```

## How it works

**Tsai-Wu**: quadratic interaction `F₁σ₁ + F₂σ₂ + F₁₁σ₁² + F₂₂σ₂² + F₆₆τ₁₂² + 2F₁₂σ₁σ₂ = 1`, where the F coefficients are derived from the strength values. **Tsai-Hill**: `(σ₁/X)² − σ₁σ₂/X² + (σ₂/Y)² + (τ₁₂/S)² = 1`. **Hashin**: separate fibre and matrix failure modes in tension and compression. FI < 1 means no failure.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `tsai_wu(sigma, strengths)` | `FailureResult` | Tsai-Wu failure index |
| `tsai_hill(sigma, strengths)` | `FailureResult` | Tsai-Hill failure index |
| `hashin(sigma, strengths)` | `FailureResult` | Hashin fibre/matrix failure modes |
| `maximum_stress(sigma, strengths)` | `FailureResult` | Maximum stress criterion |
| `first_ply_failure_analysis(laminate, load_factor_range)` | `FailureResult` | Load at first ply failure |

## Example

```python
r = tsai_wu([800e6, 20e6, 30e6], strengths)
# FailureResult(failure_index=0.73, mode='no_failure', criterion='tsai_wu')
```

## Honest caveats

Failure criteria predict initial (first-ply) failure onset; they do not model progressive damage, stiffness degradation, or ultimate failure load after first-ply failure. The Tsai-Wu F₁₂ interaction term requires biaxial test data; a default of `F₁₂ = −0.5 √(F₁₁ F₂₂)` is used when not supplied. Delamination between plies is not captured by in-plane criteria.

## References

- Tsai & Wu, "A general theory of strength for anisotropic materials," *J. Compos. Mater.* 5(1), 1971.
- Hashin, "Failure criteria for unidirectional composites," *J. Appl. Mech.* 47, 1980.
