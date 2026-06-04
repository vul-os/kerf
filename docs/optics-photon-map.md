# Jensen Spectral Photon Mapping

> Simulate wavelength-dependent light transport through refractive and reflective optical scenes — for dispersion, chromatic caustics, and spectral rendering.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/optics/photon_map.py`
**Shipped**: Wave 9
**LLM tools**: `optics_photon_map`, `optics_spectral_render`

---

## What it is

Photon mapping is a two-pass global illumination algorithm. In the first pass, photons are emitted from light sources and traced through the scene, recording each reflection and refraction event. In the second pass, the stored photon hits are queried at render-time shading points via a k-d tree nearest-neighbour search to estimate the local radiance.

Kerf's implementation extends Jensen's classical algorithm with per-photon wavelength tracking (380–780 nm, 5 nm bins) and Sellmeier dispersion: each photon carries a wavelength sampled from the source spectrum, and refractive indices are computed per wavelength using Sellmeier coefficients for common optical glasses (BK7, F2, LASFN9). This enables accurate simulation of chromatic dispersion, rainbow caustics, and spectral beam splitting.

## How to use it

### From chat (natural language)

> "Simulate the caustic pattern cast by a BK7 prism with sunlight, 50000 photons"

The LLM calls `optics_photon_map` with the scene and light source spec.

### From Python

```python
from kerf_cad_core.optics.photon_map import (
    emit_photons, trace_photons, PhotonMap, Light,
    material_from_glass, RefractiveMaterial,
)

light = Light(position=(0,0,100), direction=(0,0,-1),
              power_watts=1.0, spectral_type="solar")
material = material_from_glass("BK7")

photons = emit_photons(light, n_photons=50000)
pmap = trace_photons(photons, scene_surfaces, materials=[material])

print(f"Stored {pmap.n_stored} photon hits")
caustic_img = pmap.render_caustic_image(detector_plane_z=0.0,
                                         width_mm=50, resolution=256)
```

### From an LLM tool spec

```json
{"tool": "optics_photon_map", "n_photons": 50000, "glass": "BK7",
 "light_type": "solar", "detector_z": 0.0}
```

## How it works

Photon emission samples directions from a light source (cosine-weighted hemisphere or spotlight cone). Each photon carries a wavelength drawn from the source's spectral power distribution. At each surface intersection, a Russian-roulette decision chooses between absorption, reflection, and refraction weighted by the surface reflectance. Refraction uses Snell's law with the wavelength-dependent Sellmeier index n(λ). Hit positions and power are stored in a photon map (k-d tree). Caustic images are rendered by querying the photon map with a fixed-radius kernel over a detector plane.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `emit_photons(light, n_photons)` | `List[Photon]` | Sample photons from light source |
| `trace_photons(photons, surfaces, materials)` | `PhotonMap` | Trace and store hits |
| `material_from_glass(name)` | `RefractiveMaterial` | Sellmeier glass material |
| `sellmeier_n_from_coeffs(wavelength_nm, B, C)` | `float` | Refractive index at wavelength |

`PhotonMap` methods: `query_k_nearest(pos, k)`, `render_caustic_image(...)`.

## Example

```python
mat = material_from_glass("F2")  # flint glass
print(f"n at 589nm: {mat.n_at(589):.5f}")  # e.g. 1.62004
```

## Honest caveats

Monte Carlo photon tracing requires large photon counts (> 100k) for smooth caustic patterns — low counts produce grainy images. The k-d tree nearest-neighbour search uses a fixed-radius approach that may over-smooth sharp caustic edges. Spectral photon mapping simulates wavelength-dependent dispersion but not wave-optics effects (diffraction, interference); for those, use the diffraction PSF module.

## References

- Jensen (1996). "Global illumination using photon maps." *Eurographics Rendering Workshop*.
- Sellmeier (1871). "Zur Erklärung der abnormen Farbenfolge im Spectrum einiger Substanzen." *Annalen der Physik* 219(6).
