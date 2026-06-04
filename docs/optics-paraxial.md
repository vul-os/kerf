# Paraxial Optics and Gaussian Beam

*Domain: Optics · Module: `packages/kerf-optics/src/kerf_optics/` · Shipped: Wave 9*

## Overview

Paraxial ray transfer matrix (ABCD matrix) optics for sequential lens systems, Gaussian beam propagation through optical elements, modulation transfer function (MTF) calculation, wavefront tolerancing via Zernike polynomial expansion, and non-sequential stray-light path enumeration. All computations are pure Python + NumPy; no Zemax or CODE V runtime required.

## When to use

- Back-of-envelope lens system design (EFL, BFD, image distance, magnification).
- Gaussian beam waist tracking through a sequence of lenses and spaces.
- MTF estimation for a diffraction-limited or aberrated system.
- Tolerancing a lens system for wavefront error budget allocation.

## API

```python
from kerf_optics.ray_transfer import (
    thin_lens, free_space, flat_refractive_surface,
    system_matrix, cardinal_points,
)
from kerf_optics.gaussian import (
    GaussianBeam, propagate_through_system,
)
from kerf_optics.mtf import compute_mtf
from kerf_optics.tolerancing import tolerance_budget

# Sequential lens system
M = system_matrix([
    free_space(d=50.0),
    thin_lens(f=100.0),
    free_space(d=200.0),
])
cp = cardinal_points(M, n_obj=1.0, n_img=1.0)

# Gaussian beam propagation
beam = GaussianBeam(wavelength_um=0.633, w0_mm=0.5, z0_mm=0.0)
beam_out = propagate_through_system(beam, [
    free_space(d=50.0), thin_lens(f=100.0), free_space(d=150.0),
])
```

## LLM tools

`optics_paraxial_design`, `optics_gaussian_beam`, `optics_mtf`

## References

- Saleh & Teich, *Fundamentals of Photonics*, 3rd ed. (2019).
- Goodman, *Introduction to Fourier Optics*, 4th ed. (2017).
- ISO 10110, *Optics and photonics — Preparation of drawings for optical elements and systems*.

## Honest caveats

The ray transfer matrix formalism is valid in the paraxial (small-angle) approximation. Third-order Seidel aberrations (spherical, coma, astigmatism, field curvature, distortion) are not computed by the matrix method — use the physical optics propagator (`pop.py`) for aberration analysis. Non-sequential stray-light enumeration is combinatorial and may be slow for systems with many surfaces.
