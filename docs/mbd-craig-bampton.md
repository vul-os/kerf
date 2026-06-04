# Craig-Bampton Component Mode Synthesis

> Reduce a flexible finite-element body to a compact modal super-element for MBD simulation.

**Module**: `packages/kerf-mates/src/kerf_mates/mbd/flexible_body.py`
**Shipped**: Wave 9C3
**LLM tools**: `craig_bampton_reduce`

---

## What it is

Craig-Bampton (CB) Component Mode Synthesis (CMS) reduces a flexible body's full finite-element model to a compact super-element consisting of boundary-node degrees of freedom and a small set of fixed-interface normal modes. The reduced model preserves the dynamic response at boundary nodes while dramatically reducing the number of DOFs, enabling flexible-body MBD simulation at engineering timescales.

## How to use it

### From chat

> "Reduce my connecting-rod FE model to 6 boundary DOFs and 10 fixed-interface modes for MBD."

### From Python

```python
from kerf_mates.mbd.flexible_body import FlexBody, craig_bampton_reduce

body = FlexBody(
    K=stiffness_matrix,       # (n_dof × n_dof) sparse or dense
    M=mass_matrix,            # (n_dof × n_dof)
    boundary_dofs=[0,1,2,3,4,5],  # indices of interface DOFs
    n_modes=10,               # number of fixed-interface modes to retain
)
reduced = craig_bampton_reduce(body)
print(reduced.K_cb.shape, reduced.M_cb.shape)
# (16, 16) — 6 boundary DOFs + 10 mode DOFs
```

### From an LLM tool spec

```json
{"tool": "craig_bampton_reduce", "input": {"K": [[...]], "M": [[...]], "boundary_dofs": [0,1,2,3,4,5], "n_modes": 10}}
```

## How it works

Craig-Bampton partitions DOFs into boundary (b) and interior (i) sets. Static constraint (attachment) modes are formed by the static displacement of interior DOFs due to unit displacement at each boundary DOF: `Ψ = -K_ii⁻¹ K_ib`. Fixed-interface normal modes `Φ_n` are the lowest `n_modes` eigenvectors of the constrained interior system. The reduced mass and stiffness matrices are assembled in the (Ψ, Φ_n) basis.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `craig_bampton_reduce(body)` | `FlexBody` | Reduced CB super-element |
| `FlexBody(K, M, boundary_dofs, n_modes)` | instance | Full FE body specification |
| `step_flex_body(state, body, dt, forces)` | `FlexBodyState` | Integrate CB super-element one time step |

## Example

```python
reduced = craig_bampton_reduce(body)
# FlexBody with K_cb(16×16), M_cb(16×16), modal_freqs=[45.2, 83.1, ...] Hz
```

## Honest caveats

The reduction quality depends on how many modes are retained; 10–20 modes are adequate for low-frequency MBD simulation but may miss high-frequency excitation from impact loads. The boundary DOF selection should include all interface points that connect to other MBD bodies. The Cholesky solver used internally requires positive-definite interior stiffness; structures with rigid-body modes require additional constraint or mass regularisation.

## References

- Craig & Bampton, "Coupling of Substructures for Dynamic Analysis," *AIAA J.* 6(7), 1968.
- de Klerk, Rixen & Voormeeren, "General Framework for Dynamic Substructuring," *AIAA J.* 46(5), 2008.
