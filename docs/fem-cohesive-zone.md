# Cohesive Zone Model

> Simulate crack initiation and propagation using bilinear, exponential, or PPR traction-separation laws.

**Module**: `packages/kerf-fem/src/kerf_fem/fracture/cohesive_zone.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

Cohesive Zone Models (CZM) simulate fracture by introducing a traction-separation law on a predefined crack plane. As the crack opens, cohesive tractions resist separation until the critical opening displacement is reached, at which point the traction drops to zero and the crack propagates. Three laws are implemented: bilinear, exponential (Xu-Needleman), and Park-Paulino-Roesler (PPR).

## How to use it

### From chat

> "Compute the cohesive traction at a crack opening of 0.05 mm using a bilinear law with Gc = 500 J/m²."

### From Python

```python
from kerf_fem.fracture.cohesive_zone import (
    CohesiveZoneMaterial, traction_separation_bilinear,
    traction_separation_exponential, cohesive_fracture_energy,
)

mat = CohesiveZoneMaterial(
    sigma_max=50e6,    # cohesive strength (Pa)
    delta_c=0.001,     # critical crack opening (m)
    Gc=500.0,          # fracture energy (J/m²)
    mode="mode_I",
)
delta = 0.0005  # current opening displacement (m)

T_bilinear = traction_separation_bilinear(mat, delta)
T_exp      = traction_separation_exponential(mat, delta)
print(f"Bilinear traction: {T_bilinear/1e6:.1f} MPa")
print(f"Exponential traction: {T_exp/1e6:.1f} MPa")

Gc_check = cohesive_fracture_energy(mat)
print(f"Gc = {Gc_check:.1f} J/m²")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "cohesive_zone", "sigma_max": 50e6, "delta_c": 0.001, "Gc": 500, "mode": "mode_I"}}
```

## How it works

**Bilinear**: linear loading from 0 to `sigma_max` at `delta_0 = Gc / (0.5 × sigma_max)` (penalty stiffness regime), then linear softening to zero at `delta_c`. **Exponential (Xu-Needleman)**: `T = sigma_max × (delta/delta_n) × exp(1 − delta/delta_n)`. **PPR**: polynomial form matching both `sigma_max` and `Gc` independently with shape parameters. The area under the T-δ curve equals `Gc`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `traction_separation_bilinear(mat, delta)` | `float` | Bilinear cohesive traction |
| `traction_separation_exponential(mat, delta)` | `float` | Xu-Needleman exponential traction |
| `park_paulino_roesler(mat, delta)` | `float` | PPR traction |
| `cohesive_fracture_energy(mat)` | `float` | Verify Gc from law parameters |

## Example

```python
T = traction_separation_bilinear(mat, delta=0.0005)
# 25.0 MPa (at half the critical opening, bilinear softening)
```

## Honest caveats

The CZM requires a predefined crack path; the module does not automatically determine crack initiation location. Mode mixity (combined mode-I and mode-II) requires the mixed-mode PPR law or a separate mode-II cohesive strength, not implemented here. The traction-separation law parameters (`sigma_max`, `Gc`, `delta_c`) must be calibrated from fracture tests and are material/interface-specific.

## References

- Barenblatt, "The mathematical theory of equilibrium cracks in brittle fracture," *Adv. Appl. Mech.* 7, 1962.
- Xu & Needleman, "Void nucleation by inclusion debonding in a crystal matrix," *Model. Simul. Mater.* 1, 1993.
- Park, Paulino & Roesler, "A unified potential-based cohesive model," *J. Mech. Phys. Solids* 57, 2009.
