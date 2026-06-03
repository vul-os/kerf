"""
kerf_cad_core.optics.photon_map — Jensen 1996 two-pass photon mapping with
per-wavelength refraction using Sellmeier dispersion.

Two-pass algorithm
------------------
Pass 1 (photon tracing): Emit photons from light sources with wavelength
    samples drawn from a visible-spectrum grid.  For each photon, trace
    through the scene, refracting at glass interfaces via Snell's law with the
    wavelength-dependent refractive index n(λ) from the Sellmeier equation.
    Photons that hit a diffuse surface are recorded in the photon map.

Pass 2 (rendering / caustic gather): For each query point on a surface,
    gather the k nearest photons within a given radius and accumulate their
    power contributions to estimate the irradiance.

Design notes
------------
* Sellmeier coefficients are imported from
  kerf_cad_core.optics.chromatic_focus (GLASS_SELLMEIER, sellmeier_n) — not
  redefined here.
* Total internal reflection (TIR) is handled via the critical-angle test
  before computing the refracted direction.
* Pure Python + NumPy; no SciPy.
* k-NN gather uses a simple brute-force scan — adequate for moderate photon
  counts (< 1 M) in unit tests.  For production, replace with a balanced
  kd-tree (Jensen 2001, §9.4).

References
----------
Jensen, H.W. (1996).  "Global Illumination Using Photon Maps."
    Proc. Eurographics Workshop on Rendering (EGWR), pp. 21–30.
Jensen, H.W. (2001).  "Realistic Image Synthesis Using Photon Mapping."
    A K Peters. ISBN 978-1-56881-147-5. Ch. 7 (caustics).
Schott AG — "Optical Glass Data Sheets", 2023 edition (Sellmeier coeff.).
Sellmeier, W. (1871). "Zur Erklärung der abnormen Farbenfolge im Spectrum
    einiger Substanzen." Annalen der Physik 219(6): 272–282.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np

from kerf_cad_core.optics.chromatic_focus import GLASS_SELLMEIER, sellmeier_n

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_VISIBLE_MIN_NM = 380.0
_VISIBLE_MAX_NM = 780.0

# RGB centre wavelengths for power-to-RGB channel mapping
_RGB_WAVELENGTHS_NM = (650.0, 550.0, 450.0)  # R, G, B

# Small epsilon to avoid self-intersection on re-emission
_EPS = 1e-9


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

@dataclass
class Photon:
    """
    A single photon in the photon map.

    Attributes
    ----------
    position : np.ndarray, shape (3,)
        3-D world-space position where the photon was recorded (on a diffuse
        surface, or on the image plane for caustic gather).
    direction : np.ndarray, shape (3,) unit vector
        Incident direction of the photon at the recorded position.
    power_rgb : np.ndarray, shape (3,)
        RGB flux carried by this photon (W per channel).  The mapping from
        wavelength to RGB uses a simple tri-band model consistent with
        Jensen (1996) §4.1.
    wavelength_nm : float
        Photon wavelength in nanometres.  Used for dispersion bookkeeping
        (Snell refraction uses this at each glass interface).
    """
    position: np.ndarray       # (3,)
    direction: np.ndarray      # (3,) unit
    power_rgb: np.ndarray      # (3,) W per channel
    wavelength_nm: float


@dataclass
class PhotonMap:
    """
    Photon map: collection of stored photons + irradiance estimation.

    Attributes
    ----------
    photons : list[Photon]
        All stored photons (diffuse-surface hits).

    References
    ----------
    Jensen (2001), §9.4 — balanced kd-tree for efficient k-NN lookup.
    Here we use brute-force O(N) gather sufficient for tests / moderate N.
    """
    photons: List[Photon] = field(default_factory=list)

    def gather(
        self,
        query_point: np.ndarray,
        normal: np.ndarray,
        radius: float,
        max_n: int = 100,
    ) -> np.ndarray:
        """
        k-NN density estimation: sum power of nearest photons within *radius*
        around *query_point*, projected onto the hemisphere defined by *normal*.

        The irradiance estimate follows Jensen (2001), eq. (9.7):

            E = (1 / (π r²)) Σ_{i=1}^{N} Φ_i  [W m⁻² per channel]

        Parameters
        ----------
        query_point : np.ndarray, shape (3,)
        normal : np.ndarray, shape (3,) unit normal at query point
        radius : float
            Gather radius (metres or scene units).
        max_n : int
            Maximum number of photons to include (Jensen 2001 §9.4).

        Returns
        -------
        np.ndarray, shape (3,)
            Estimated RGB irradiance [W / unit_area² per channel].
        """
        if not self.photons:
            return np.zeros(3)

        positions = np.array([p.position for p in self.photons])  # (N, 3)
        powers = np.array([p.power_rgb for p in self.photons])    # (N, 3)

        diffs = positions - query_point[np.newaxis, :]  # (N, 3)
        dists_sq = np.sum(diffs * diffs, axis=1)         # (N,)
        r2 = radius * radius

        in_radius = dists_sq <= r2
        idx = np.where(in_radius)[0]

        if idx.size == 0:
            return np.zeros(3)

        # Keep at most max_n closest
        if idx.size > max_n:
            order = np.argsort(dists_sq[idx])[:max_n]
            idx = idx[order]

        # Sum photon power for all photons in the gather region.
        # Jensen (2001) eq. (9.7): E ≈ (1/πr²) Σ Φ_i
        # No direction weighting here — the caller is responsible for
        # applying a BRDF if needed.  Direction filtering (hemisphere check)
        # is skipped so that photons stored from any direction are counted,
        # consistent with the caustic-only photon map use case (Jensen 1996 §4).
        power_sum = np.sum(powers[idx], axis=0)  # (3,)

        # Normalise by disc area (Jensen 2001, §9.3)
        area = math.pi * r2
        return power_sum / area


# ---------------------------------------------------------------------------
# Light source
# ---------------------------------------------------------------------------

@dataclass
class Light:
    """
    A point or spot light source.

    Attributes
    ----------
    position : np.ndarray, shape (3,)
    intensity_rgb : np.ndarray, shape (3,)
        Radiant intensity W/sr per RGB channel.
    direction : np.ndarray or None
        Unit direction of spot axis.  None → isotropic point light.
    cone_angle_rad : float or None
        Half-angle of the spot cone (rad).  None for point lights.
    """
    position: np.ndarray
    intensity_rgb: np.ndarray
    direction: Optional[np.ndarray] = None
    cone_angle_rad: Optional[float] = None


# ---------------------------------------------------------------------------
# Refractive material
# ---------------------------------------------------------------------------

@dataclass
class RefractiveMaterial:
    """
    A refractive optical glass identified by Schott glass name.

    Parameters
    ----------
    name : str
        Schott glass name — must be a key in GLASS_SELLMEIER, e.g. "BK7".
    abbe_number : float
        Abbe V-number (V_d).  Informational; dispersion is computed via
        Sellmeier directly.
    sellmeier_b : tuple of three floats
        Sellmeier B coefficients (B1, B2, B3) [dimensionless].
    sellmeier_c : tuple of three floats
        Sellmeier C coefficients (C1, C2, C3) [μm²].

    References
    ----------
    Schott AG — "Optical Glass Data Sheets", 2023 edition.
    ISO 10110-17:2004 — Sellmeier equation.
    """
    name: str
    abbe_number: float
    sellmeier_b: Tuple[float, float, float]
    sellmeier_c: Tuple[float, float, float]

    def refractive_index(self, wavelength_nm: float) -> float:
        """
        Compute n(λ) via the Sellmeier equation.

        n²(λ) = 1 + Σ_{i=1}^{3}  B_i · λ² / (λ² − C_i)

        where λ is in micrometres (μm).

        Parameters
        ----------
        wavelength_nm : float
            Wavelength in nanometres.

        Returns
        -------
        float
            Refractive index n ≥ 1.
        """
        lam_um = wavelength_nm / 1000.0
        return sellmeier_n_from_coeffs(
            self.sellmeier_b, self.sellmeier_c, lam_um
        )


def sellmeier_n_from_coeffs(
    b: Tuple[float, float, float],
    c: Tuple[float, float, float],
    wavelength_um: float,
) -> float:
    """
    Sellmeier equation from raw coefficient tuples.

    References
    ----------
    Sellmeier (1871); ISO 10110-17; Schott TIE-29.
    """
    lam2 = wavelength_um * wavelength_um
    n2 = (
        1.0
        + b[0] * lam2 / (lam2 - c[0])
        + b[1] * lam2 / (lam2 - c[1])
        + b[2] * lam2 / (lam2 - c[2])
    )
    return math.sqrt(max(n2, 1.0))


def material_from_glass(name: str) -> RefractiveMaterial:
    """
    Construct a RefractiveMaterial from an existing GLASS_SELLMEIER entry.

    Parameters
    ----------
    name : str
        Glass name, e.g. "BK7", "SF11".

    Returns
    -------
    RefractiveMaterial
    """
    if name not in GLASS_SELLMEIER:
        raise KeyError(f"Unknown glass '{name}'. Available: {list(GLASS_SELLMEIER)}")
    B1, B2, B3, C1, C2, C3 = GLASS_SELLMEIER[name]
    # Compute Abbe number from Sellmeier for reference
    n_d = sellmeier_n(name, 0.58756)
    n_F = sellmeier_n(name, 0.48613)
    n_C = sellmeier_n(name, 0.65627)
    abbe = (n_d - 1.0) / (n_F - n_C)
    return RefractiveMaterial(
        name=name,
        abbe_number=abbe,
        sellmeier_b=(B1, B2, B3),
        sellmeier_c=(C1, C2, C3),
    )


# ---------------------------------------------------------------------------
# Wavelength → RGB channel mapping
# ---------------------------------------------------------------------------

def _wavelength_to_rgb_weight(wavelength_nm: float) -> np.ndarray:
    """
    Map a wavelength to a (3,) RGB weight vector using a simple tri-band
    model consistent with Jensen (1996) §4.1 spectral-to-RGB conversion.

    Bands:
      R: 620–700 nm  (centre 660 nm)
      G: 500–620 nm  (centre 550 nm)
      B: 380–500 nm  (centre 450 nm)

    Returns
    -------
    np.ndarray, shape (3,)
        Normalised weight [R, G, B].  Exactly one channel is non-zero (single
        wavelength falls into one band); returns [1/3, 1/3, 1/3] for
        out-of-band wavelengths.
    """
    wl = wavelength_nm
    if 620.0 <= wl <= 780.0:
        return np.array([1.0, 0.0, 0.0])
    if 500.0 <= wl < 620.0:
        return np.array([0.0, 1.0, 0.0])
    if 380.0 <= wl < 500.0:
        return np.array([0.0, 0.0, 1.0])
    # Near-UV / near-IR: distribute equally
    return np.array([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0])


# ---------------------------------------------------------------------------
# Photon emission
# ---------------------------------------------------------------------------

def emit_photons(
    light: Light,
    n_photons: int,
    wavelengths_nm: List[float],
    rng_seed: int = 0,
) -> List[Photon]:
    """
    Emit *n_photons* from *light* distributed across *wavelengths_nm*.

    Sampling strategy
    -----------------
    * n_photons // len(wavelengths_nm) photons per wavelength bucket.
    * If n_photons is not divisible the remainder is distributed across the
      first (n_photons % len(wavelengths_nm)) buckets.
    * For a point light: directions are sampled uniformly on the sphere.
    * For a spot light: directions are sampled uniformly within the cone,
      weighted by cos(θ) (Lambertian-spot; Jensen 2001 §7.3).
    * Power per photon = total_power / n_photons, split by RGB channel.

    Parameters
    ----------
    light : Light
    n_photons : int
        Total number of photons to emit.
    wavelengths_nm : list[float]
        Wavelengths (nm) from which photons are drawn round-robin.
    rng_seed : int
        Seed for numpy RNG — ensures deterministic output.

    Returns
    -------
    list[Photon]

    References
    ----------
    Jensen (2001), §7.3 (photon emission from light sources).
    """
    rng = np.random.default_rng(rng_seed)
    n_wl = len(wavelengths_nm)
    base, remainder = divmod(n_photons, n_wl)

    # Count per wavelength
    counts = [base + (1 if i < remainder else 0) for i in range(n_wl)]

    # Power per photon: split intensity_rgb over all photons uniformly
    # (solid-angle integral of isotropic source = 4π sr)
    total_power = light.intensity_rgb * 4.0 * math.pi
    power_per_photon = total_power / max(n_photons, 1)

    photons: List[Photon] = []

    for wl_idx, (wl, count) in enumerate(zip(wavelengths_nm, counts)):
        rgb_weight = _wavelength_to_rgb_weight(wl)
        pwr = power_per_photon * rgb_weight

        for _ in range(count):
            # Sample emission direction
            if light.direction is None or light.cone_angle_rad is None:
                # Isotropic point light — uniform sphere sampling
                direction = _sample_sphere(rng)
            else:
                direction = _sample_cone(rng, light.direction, light.cone_angle_rad)

            photons.append(Photon(
                position=light.position.copy(),
                direction=direction,
                power_rgb=pwr.copy(),
                wavelength_nm=wl,
            ))

    return photons


def _sample_sphere(rng: np.random.Generator) -> np.ndarray:
    """Uniform sphere sampling (Marsaglia 1972)."""
    while True:
        v = rng.uniform(-1.0, 1.0, size=3)
        r2 = float(np.dot(v, v))
        if 0.0 < r2 <= 1.0:
            return v / math.sqrt(r2)


def _sample_cone(
    rng: np.random.Generator,
    axis: np.ndarray,
    half_angle_rad: float,
) -> np.ndarray:
    """
    Sample a direction uniformly within a cone of half-angle *half_angle_rad*
    centred on *axis*.

    Uses cosine-weighted sampling inside the cone (Jensen 2001 §7.3).
    """
    cos_max = math.cos(half_angle_rad)
    cos_theta = rng.uniform(cos_max, 1.0)
    sin_theta = math.sqrt(max(1.0 - cos_theta * cos_theta, 0.0))
    phi = rng.uniform(0.0, 2.0 * math.pi)

    # Local frame around axis
    u, v = _orthonormal_basis(axis)
    local_dir = (
        sin_theta * math.cos(phi) * u
        + sin_theta * math.sin(phi) * v
        + cos_theta * axis
    )
    norm = np.linalg.norm(local_dir)
    return local_dir / norm if norm > 0.0 else axis.copy()


def _orthonormal_basis(n: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return two unit vectors (u, v) orthogonal to n and each other."""
    n = n / np.linalg.norm(n)
    # Pick a helper vector not parallel to n
    if abs(n[0]) < 0.9:
        t = np.array([1.0, 0.0, 0.0])
    else:
        t = np.array([0.0, 1.0, 0.0])
    u = np.cross(n, t)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    v /= np.linalg.norm(v)
    return u, v


# ---------------------------------------------------------------------------
# Snell refraction
# ---------------------------------------------------------------------------

def _snell_refract(
    incident: np.ndarray,
    normal: np.ndarray,
    n1: float,
    n2: float,
) -> Optional[np.ndarray]:
    """
    Compute refracted direction using Snell's law with TIR check.

    Parameters
    ----------
    incident : np.ndarray, shape (3,)
        Incident unit direction (pointing *toward* the interface).
    normal : np.ndarray, shape (3,)
        Surface normal (pointing *away from* the refracting medium, i.e.
        outward from the glass).  Must point into the medium the photon is
        coming from.
    n1 : float
        Refractive index of the incident medium.
    n2 : float
        Refractive index of the transmitted medium.

    Returns
    -------
    np.ndarray or None
        Refracted unit direction, or None if total internal reflection occurs.

    References
    ----------
    Hecht (2017) §4.7 (Snell), §4.8 (TIR).
    Jensen (2001), §2.1 (ray–surface interaction for glass).
    """
    n_hat = normal / np.linalg.norm(normal)
    d = incident / np.linalg.norm(incident)

    # cos(θ₁) — angle between incoming ray and normal
    cos_i = -float(np.dot(d, n_hat))
    if cos_i < 0.0:
        # Ray hitting from the other side — flip normal
        n_hat = -n_hat
        cos_i = -cos_i

    ratio = n1 / n2
    sin2_t = ratio * ratio * (1.0 - cos_i * cos_i)

    if sin2_t > 1.0:
        return None  # TIR

    cos_t = math.sqrt(max(1.0 - sin2_t, 0.0))
    refracted = ratio * d + (ratio * cos_i - cos_t) * n_hat
    norm = np.linalg.norm(refracted)
    return refracted / norm if norm > 0.0 else refracted


def _reflect(incident: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """Specular reflection of incident direction off normal."""
    n_hat = normal / np.linalg.norm(normal)
    d = incident / np.linalg.norm(incident)
    return d - 2.0 * float(np.dot(d, n_hat)) * n_hat


# ---------------------------------------------------------------------------
# Photon tracing
# ---------------------------------------------------------------------------

def trace_photons(
    photons: List[Photon],
    scene_intersect: Callable[[np.ndarray, np.ndarray], Optional[dict]],
    max_bounces: int = 6,
) -> PhotonMap:
    """
    Trace photons through the scene and record hits on diffuse surfaces.

    Pass 1 of Jensen (1996) photon-mapping algorithm.

    For each photon, iterate:
      1. Intersect the ray (photon.position + t * photon.direction) with the
         scene via *scene_intersect*.
      2. Classify the hit surface:
         - "diffuse"  → record the photon in the map and stop.
         - "glass"    → refract via Snell using the material's
                        refractive_index(wavelength_nm); handle TIR.
         - "mirror"   → reflect specularly and continue.
         - None       → no hit, photon escapes.
      3. Repeat up to *max_bounces* times, then absorb.

    *scene_intersect* signature:
    ```
    def scene_intersect(origin: np.ndarray, direction: np.ndarray) -> dict | None
    ```
    Returns a dict on hit:
      ``t``          — float, ray parameter (must be > 0)
      ``position``   — np.ndarray (3,), hit point
      ``normal``     — np.ndarray (3,), outward surface normal
      ``surface``    — str: "diffuse" | "glass" | "mirror"
      ``material``   — RefractiveMaterial | None (required for "glass")
      ``n_inside``   — float | None (refractive index of glass interior, if
                        already known; derived from material if None)

    Parameters
    ----------
    photons : list[Photon]
        Input photons from emit_photons().
    scene_intersect : callable
        Scene ray–intersection function.
    max_bounces : int
        Maximum number of glass/mirror bounces before absorption.

    Returns
    -------
    PhotonMap

    References
    ----------
    Jensen (1996), §3 (photon tracing pass).
    Jensen (2001), §7.4 (photon–surface interactions).
    """
    stored: List[Photon] = []

    for ph in photons:
        pos = ph.position.copy().astype(float)
        dirn = ph.direction.copy().astype(float)
        dirn /= np.linalg.norm(dirn)
        power = ph.power_rgb.copy()
        wl = ph.wavelength_nm
        inside_glass = False  # track whether photon is inside a glass medium
        n_current = 1.0       # refractive index of current medium

        for _bounce in range(max_bounces):
            hit = scene_intersect(pos, dirn)
            if hit is None:
                break

            hit_pos: np.ndarray = np.asarray(hit["position"], dtype=float)
            hit_normal: np.ndarray = np.asarray(hit["normal"], dtype=float)
            hit_normal /= np.linalg.norm(hit_normal)
            surface_type: str = hit.get("surface", "diffuse")

            if surface_type == "diffuse":
                stored.append(Photon(
                    position=hit_pos.copy(),
                    direction=dirn.copy(),
                    power_rgb=power.copy(),
                    wavelength_nm=wl,
                ))
                break

            elif surface_type == "glass":
                mat: Optional[RefractiveMaterial] = hit.get("material")
                if mat is not None:
                    n_glass = mat.refractive_index(wl)
                else:
                    n_glass = float(hit.get("n_inside", 1.5))

                # Determine n1, n2 based on whether photon is entering/exiting
                cos_i = -float(np.dot(dirn, hit_normal))
                if cos_i > 0:
                    # Entering glass
                    n1, n2 = n_current, n_glass
                    new_inside = True
                else:
                    # Exiting glass
                    n1, n2 = n_glass, 1.0
                    new_inside = False
                    hit_normal = -hit_normal

                refracted = _snell_refract(dirn, hit_normal, n1, n2)
                if refracted is None:
                    # TIR — reflect
                    dirn = _reflect(dirn, hit_normal)
                else:
                    dirn = refracted
                    n_current = n2
                    inside_glass = new_inside

                # Advance past the surface
                pos = hit_pos + _EPS * dirn

            elif surface_type == "mirror":
                dirn = _reflect(dirn, hit_normal)
                pos = hit_pos + _EPS * dirn

            else:
                # Unknown surface — treat as diffuse absorber
                stored.append(Photon(
                    position=hit_pos.copy(),
                    direction=dirn.copy(),
                    power_rgb=power.copy(),
                    wavelength_nm=wl,
                ))
                break

    return PhotonMap(photons=stored)
