# Composite Laminate Layup

> Classical Laminate Theory (CLT) ABD matrix, failure-index computation, and flat-to-surface drape simulation for fibre-reinforced composites.

**Module**: `packages/kerf-composites/src/kerf_composites/layup.py`, `clt.py`, `failure.py`, `drape.py`
**Shipped**: Wave 9
**LLM tools**: `composites_clt`, `composites_failure`, `composites_drape`

---

## What it is

Composites layup design requires three concurrent decisions: stacking sequence (ply angles), material selection, and drapeability. Getting any one wrong leads to delamination, warp after cure, or off-spec mechanical properties. This module gives you: (1) the CLT ABD stiffness matrix for any laminate, (2) Tsai-Wu and max-stress failure indices under in-plane loads, and (3) a geodesic drape preview to catch shear lock-up before the layup is cut.

## How to use it

### From chat

> "Calculate the CLT stiffness matrix and Tsai-Wu failure index for a [0/±45/90]s T300/5208 carbon-epoxy laminate, 0.125 mm plies, under Nx = 500 N/mm."

### From Python

```python
from kerf_composites.layup import LaminateLayup, T300_5208
from kerf_composites.clt import build_abd, laminate_stiffness
from kerf_composites.failure import tsai_wu_index

layup = LaminateLayup.from_angles(
    angles=[0, 45, -45, 90, 90, -45, 45, 0],
    material=T300_5208,
    ply_thickness=0.125
)
abd = build_abd(layup)
result = laminate_stiffness(abd, Nx=500.0, Ny=0.0, Nxy=0.0)
fi = tsai_wu_index(result["ply_stresses"], T300_5208)
print("Max Tsai-Wu index:", max(fi))
```

### From an LLM tool spec

```json
{"angles": [0, 45, -45, 90, 90, -45, 45, 0],
 "material": "T300_5208", "ply_thickness": 0.125,
 "loads": {"Nx": 500, "Ny": 0, "Nxy": 0}}
```

## How it works

CLT builds the laminate stiffness via standard ply-transformation: each ply's reduced stiffness matrix Q is rotated to the laminate axes using the transformation matrix T(θ), then integrated through the thickness to form A (extensional), B (coupling), and D (bending) sub-matrices. Tsai-Wu failure index combines all six components of the stress state into a single scalar: F₁σ₁ + F₂σ₂ + F₁₁σ₁² + F₂₂σ₂² + F₆₆τ₁₂² + 2F₁₂σ₁σ₂ ≤ 1. Drape uses a discrete pin-jointed fishing-net algorithm placing nodes at geodesic distances from pinned rows/columns on the target surface.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `build_abd(layup)` | `np.ndarray` (6×6) | ABD stiffness matrix |
| `laminate_stiffness(abd, Nx, Ny, Nxy)` | `dict` | Mid-plane strains + ply stresses |
| `tsai_wu_index(ply_stresses, material)` | `list[float]` | Tsai-Wu FI per ply |
| `drape_flat_to_surface(surface_fn, u_range, v_range, nu, nv)` | `DrapeResult` | Geodesic drape mapping |

## Example

```python
# Check shear lock-up: max shear angle < 45° is the rule of thumb
from kerf_composites.drape import drape_flat_to_surface
import numpy as np

surface = lambda u, v: (u, v, 0.01 * u**2)  # parabolic crown
dr = drape_flat_to_surface(surface, (0,500), (0,300), nu=20, nv=12)
print("Max shear angle:", dr.shear_angles.max(), "°")
```

## Honest caveats

CLT assumes plane stress (σ₃ = τ₁₃ = τ₂₃ = 0); through-thickness interlaminar stresses need a separate 3D analysis. The Tsai-Wu criterion requires the interaction coefficient F₁₂; this module defaults to F₁₂ = −0.5√(F₁₁·F₂₂) (Tsai-Hahn suggestion) — verify for your specific material. Drape is an inextensible-fabric approximation; extensible or pre-preg materials need FEA drape.

## References

- Reddy, J.N. (2003). *Mechanics of Laminated Composite Plates and Shells*, 2nd ed. CRC. §1–3.
- Tsai, S.W. & Wu, E.M. (1971). A general theory of strength for anisotropic materials. *J. Compos. Mater.* 5(1), 58–80.
