# Classical Laminate Theory (CLT)

> Compute A/B/D stiffness matrices, ply stresses, and laminate response for fibre-composite laminates.

**Module**: `packages/kerf-fem/src/kerf_fem/composites/laminate_classical.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

Classical Laminate Theory (CLT) computes the in-plane (`A`), coupling (`B`), and bending stiffness (`D`) matrices for a layered fibre-composite laminate. From the ABD matrix and applied mid-plane strains and curvatures, it computes ply-level stresses and strains in both laminate and material coordinates. The `analyze_laminate` function is the primary entry point.

## How to use it

### From chat

> "Compute the ABD matrix and maximum ply stress for a [0/90/±45]_s CFRP laminate under 1000 N/m in-plane load."

### From Python

```python
from kerf_fem.composites.laminate_classical import LaminaPly, Laminate, analyze_laminate

ply = LaminaPly(
    E1=140e9, E2=10e9, G12=5e9, nu12=0.3,
    thickness_mm=0.125,
)
laminate = Laminate(
    plies=[ply]*8,
    angles_deg=[0, 90, 45, -45, -45, 45, 90, 0],  # symmetric
)
result = analyze_laminate(
    laminate=laminate,
    N={"Nxx": 1000, "Nyy": 0, "Nxy": 0},  # N/m
    M={"Mxx": 0, "Myy": 0, "Mxy": 0},     # N
)
print(result.A_matrix)
print(result.max_ply_stress_mpa)
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "clt_laminate", "angles_deg": [0, 90, 45, -45], "Nxx": 1000}}
```

## How it works

Each ply contributes to the A, B, D matrices via numerical integration through the laminate thickness using the standard CLT summation: `A_ij = Σ Q̄_ij^(k) × h^(k)`, `B_ij = Σ Q̄_ij^(k) × z_k × h^(k)`, `D_ij = Σ Q̄_ij^(k) × z_k² × h^(k)`. The ply transformed stiffness `Q̄` is computed by rotating the ply principal stiffness matrix by the fibre angle. Mid-plane strains and curvatures are found by solving the ABD system.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `analyze_laminate(laminate, N, M)` | `LaminateResponse` | ABD matrix, ply stresses, mid-plane strains |
| `LaminaPly(E1, E2, G12, nu12, thickness_mm)` | instance | Single ply properties |
| `Laminate(plies, angles_deg)` | instance | Laminate stack |

## Example

```python
result = analyze_laminate(laminate, N={"Nxx": 1000}, M={})
# LaminateResponse(A=[[...]], B=[[...]], D=[[...]], 
#                  max_ply_stress_mpa=142.3, mid_plane_strain_xx=7.4e-6)
```

## Honest caveats

CLT is a thin-plate theory; transverse shear deformation is ignored (no FSDT). It does not account for free-edge effects, delamination, or cure-induced residual stresses. Out-of-plane stresses (σ₃₃, τ₁₃, τ₂₃) are not computed. For thick laminates (t > span/10) use a higher-order shear deformation theory.

## References

- Reddy, *Mechanics of Laminated Composite Plates and Shells*, 2nd ed. (2004), Ch. 3.
- Jones, *Mechanics of Composite Materials*, 2nd ed. (1998), Ch. 4.
