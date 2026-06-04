# FEM Modal Analysis and Euler Buckling

> Compute natural frequencies, mode shapes, and Euler buckling loads for beams and columns — with a pure-Python Cholesky-Jacobi eigensolver.

**Module**: `packages/kerf-fem/src/kerf_fem/modal.py`
**Shipped**: Wave 9
**LLM tools**: `fem_run`, `fem_buckling_linear`

---

## What it is

Modal analysis identifies the natural frequencies and mode shapes of a structure — the frequencies at which it will resonate under dynamic excitation. Engineers compare these against operating excitation frequencies to ensure resonance margins and to inform damping design. Buckling analysis predicts the critical compressive load at which a slender column or plate becomes unstable.

This module solves the generalised eigenvalue problem Kφ = ω² Mφ using a Cholesky factorisation of M and a Jacobi sweep diagonalisation for the transformed symmetric eigenvalue problem. It covers Euler-Bernoulli beams (consistent mass and stiffness matrices), classical column buckling (four end conditions), and simply-supported rectangular plate first mode. For 3D modal/buckling, `fem_run` dispatches to CalculiX.

## How to use it

### From chat (natural language)

> "What are the first 3 natural frequencies of a 2m simply-supported steel beam with IPE 200 section?"

The LLM calls `fem_run` (modal) and returns the frequency table.

### From Python

```python
from kerf_fem.modal import (
    beam_natural_frequencies, euler_buckling_load,
    plate_first_mode_simply_supported,
)

# Simply-supported steel beam, IPE 200
modes = beam_natural_frequencies(
    E=200e9, I=1.943e-5, rho=7850, A=2.848e-3, L=2.0,
    supports="simply_supported", n_modes=5, n_elem=20,
)
for m in modes["modes"]:
    print(f"  f{m['mode']} = {m['freq_hz']:.2f} Hz")

# Euler buckling, fixed-free column
buck = euler_buckling_load(E=200e9, I=1.943e-5, L=3.0, K_factor=2.0)
print(f"P_cr = {buck['P_cr_N']/1000:.2f} kN")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "type": "modal", "E": 200e9, "I": 1.943e-5,
 "rho": 7850, "A": 2.848e-3, "L": 2.0, "n_modes": 5}
```

## How it works

The generalised eigenvalue problem Kφ = ω²Mφ is transformed to a standard symmetric form via Cholesky: M = LLᵀ, then K' = L⁻¹K(Lᵀ)⁻¹, solved by Jacobi sweeps (off-diagonal annihilation). Consistent mass matrices are used (exact for Euler-Bernoulli fields). Euler buckling: P_cr = π²EI / (KL)², where K is the effective-length factor (1=pin-pin, 0.5=fixed-fixed, 0.7=pin-fixed, 2=fixed-free).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `beam_natural_frequencies(E, I, rho, A, L, supports, n_modes, n_elem)` | `dict` | Modal frequencies and shapes |
| `euler_buckling_load(E, I, L, K_factor)` | `dict` | Critical buckling load |
| `plate_first_mode_simply_supported(E, nu, rho, t, a, b)` | `dict` | Plate first natural frequency |

`beam_natural_frequencies` returns `modes` list with `mode`, `freq_hz`, `omega_rad_s`, `shape`.

## Example

```python
buck = euler_buckling_load(E=200e9, I=5e-6, L=2.5, K_factor=1.0)
print(f"Pin-pin P_cr = {buck['P_cr_N']/1e3:.1f} kN")
```

## Honest caveats

The Cholesky-Jacobi solver covers 1D Euler-Bernoulli beams. Gyroscopic effects, damping, and geometric stiffness from pre-stress are not included. For 3D modal and buckling (shells, solids), use `fem_run` dispatching to CalculiX. The plate first-mode formula is the Navier series for simply-supported rectangles — other boundary conditions require numerical methods.

## References

- Thomson (1997). *Theory of Vibration with Applications*, 5th ed. Prentice Hall.
- Timoshenko & Gere (1961). *Theory of Elastic Stability*, 2nd ed. McGraw-Hill.
- Euler (1744). "De curvis elasticis" — classical column buckling.
