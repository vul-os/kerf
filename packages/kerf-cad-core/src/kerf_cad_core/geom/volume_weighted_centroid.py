"""Volume-weighted centroid and inertia tensor for B-rep bodies with
non-uniform (spatially-varying) density.

Background
----------
For a body Ω with density field ρ(r), the mass-weighted centroid and inertia
tensor are defined as volume integrals::

    M    = ∫∫∫_Ω  ρ(r)        dV
    C_i  = (1/M) ∫∫∫_Ω  r_i · ρ(r)  dV          (i ∈ {x, y, z})

    I_ij = ∫∫∫_Ω  ρ(r) · (‖r‖² δ_ij − r_i r_j)  dV

These integrals are evaluated via Monte Carlo importance sampling (uniform
over the body's bounding box, rejection-sampled to the body interior using
the signed-distance field).  Mortenson (1985) §11.5 documents the compound-
density form; the SDF point-in-body test generalises to arbitrary B-rep
shapes without requiring meshing.

API
---
compute_centroid_density_field(body, density_field, n_samples=1000)
    → CentroidResult

compute_inertia_density_field(body, density_field, n_samples=10000)
    → InertiaResult

functionally_graded_centroid(body, density_func_kind='linear_z', ...)
    → CentroidResult

References
----------
Mortenson, M.E. (1985) *Geometric Modeling*, §11.5 — compound density
integration via volume integral.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np

from kerf_cad_core.geom.brep import Body
from kerf_cad_core.geom.sdf import body_sdf, sdf_sample, _body_bbox


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CentroidResult:
    """Result of a density-weighted centroid computation.

    Attributes
    ----------
    centroid : np.ndarray, shape (3,)
        Mass-weighted centroid [x, y, z].
    total_mass : float
        Integral of ρ(r) dV over the body.
    std_error : float
        Monte Carlo standard error on the centroid estimate (each component).
        Defined as the standard deviation of the per-sample position divided
        by sqrt(accepted_samples).
    samples_used : int
        Number of interior samples that contributed to the estimate.
    """
    centroid: np.ndarray
    total_mass: float
    std_error: float
    samples_used: int


@dataclass
class InertiaResult:
    """Result of a density-weighted inertia tensor computation.

    Attributes
    ----------
    centroid : np.ndarray, shape (3,)
        Mass-weighted centroid [x, y, z] (same as CentroidResult.centroid).
    total_mass : float
        Integral of ρ(r) dV over the body.
    inertia_tensor : np.ndarray, shape (3, 3)
        Inertia tensor about the centroid.
        I = ∫ ρ(r) (‖r - C‖² 1 - (r-C)⊗(r-C)) dV
    samples_used : int
        Number of interior samples used.
    """
    centroid: np.ndarray
    total_mass: float
    inertia_tensor: np.ndarray
    samples_used: int


# ---------------------------------------------------------------------------
# Internal: bounding-box volume + SDF query helpers
# ---------------------------------------------------------------------------

def _build_point_in_body(body: Body, sdf_resolution: int = 32):
    """Pre-compute the SDF grid; return (sdf_dict, lo, hi, bbox_volume).

    The SDF grid is built once and reused across all MC samples for speed.
    """
    lo, hi = _body_bbox(body, n_uv=12)
    # Guard against degenerate (zero-volume) bounding box
    span = hi - lo
    if np.any(span < 1e-14):
        raise ValueError(
            f"Degenerate body bounding box: lo={lo}, hi={hi}. "
            "Body may have no faces or all faces are co-planar."
        )
    # Compute SDF grid (negative inside, positive outside)
    sdf = body_sdf(body, resolution=sdf_resolution, padding=0.05)
    bbox_volume = float(np.prod(span))
    return sdf, lo, hi, bbox_volume


# ---------------------------------------------------------------------------
# Public: centroid with arbitrary density field
# ---------------------------------------------------------------------------

def compute_centroid_density_field(
    body: Body,
    density_field: Callable[[np.ndarray], float],
    n_samples: int = 1000,
    *,
    _sdf_resolution: int = 32,
    rng: np.random.Generator | None = None,
) -> CentroidResult:
    """Compute the mass-weighted centroid of *body* under a spatially-varying
    density field using Monte Carlo volume integration.

    Parameters
    ----------
    body:
        A closed (watertight) :class:`~kerf_cad_core.geom.brep.Body`.
    density_field:
        Callable ``ρ(point: ndarray) → float`` where *point* is a world-space
        coordinate array of shape ``(3,)``.  Must return a non-negative scalar.
    n_samples:
        Number of Monte Carlo *candidate* samples drawn from the bounding box.
        The actual samples used are those inside the body (SDF ≤ 0).
        Default 1000; increase for tighter error bounds.
    _sdf_resolution:
        Resolution of the internal SDF grid used for point-in-body tests.
        Default 32 (adequate for most smooth bodies).
    rng:
        Optional ``numpy.random.Generator`` for reproducible results.

    Returns
    -------
    CentroidResult
        centroid, total_mass, std_error, samples_used.

    Notes
    -----
    Algorithm (Mortenson §11.5 compound-density form):

    1. Build an AABB and rejection-sample *n_samples* points uniformly.
    2. Accept points where SDF(p) ≤ 0 (inside the body).
    3. Estimate::

        M  ≈ V_bbox · (1/N_in) · Σ ρ(p_k)
        C  ≈ (1/Σ ρ_k) · Σ ρ(p_k) · p_k

       which is the standard importance-weighted MC estimator.
    4. std_error = std(ρ·p) / sqrt(N_in) scaled by bbox/M.
    """
    if rng is None:
        rng = np.random.default_rng()

    sdf, lo, hi, bbox_volume = _build_point_in_body(body, _sdf_resolution)
    span = hi - lo

    # Draw all candidate samples at once for efficiency
    pts = lo + rng.random((n_samples, 3)) * span  # (n_samples, 3)

    # Point-in-body test: SDF ≤ 0 means inside
    sdf_vals = np.array([sdf_sample(sdf, pts[i]) for i in range(n_samples)])
    inside = sdf_vals <= 0.0
    pts_in = pts[inside]
    n_in = len(pts_in)

    if n_in == 0:
        return CentroidResult(
            centroid=np.zeros(3),
            total_mass=0.0,
            std_error=float("inf"),
            samples_used=0,
        )

    # Evaluate density at each interior point
    rho = np.array([float(density_field(pts_in[i])) for i in range(n_in)])
    rho = np.maximum(rho, 0.0)  # clamp negative density to zero

    rho_sum = float(rho.sum())
    if rho_sum < 1e-30:
        # All density values are effectively zero
        return CentroidResult(
            centroid=np.zeros(3),
            total_mass=0.0,
            std_error=float("inf"),
            samples_used=n_in,
        )

    # Centroid: weighted mean of positions
    centroid = (rho[:, np.newaxis] * pts_in).sum(axis=0) / rho_sum

    # Total mass: M = V_bbox * (fraction inside) * mean(ρ over interior)
    # = V_bbox * (n_in / n_samples) * (rho_sum / n_in)
    # = V_bbox * rho_sum / n_samples
    total_mass = bbox_volume * rho_sum / n_samples

    # MC standard error on centroid: std of ρ-weighted position / sqrt(n_in)
    # Per-component variance of ρ·p / ρ_sum
    residuals = pts_in - centroid  # (n_in, 3)
    weighted_var = (rho[:, np.newaxis] * residuals**2).sum(axis=0) / rho_sum
    std_error = float(np.sqrt(weighted_var.mean()) / math.sqrt(n_in))

    return CentroidResult(
        centroid=centroid,
        total_mass=total_mass,
        std_error=std_error,
        samples_used=n_in,
    )


# ---------------------------------------------------------------------------
# Public: inertia tensor with arbitrary density field
# ---------------------------------------------------------------------------

def compute_inertia_density_field(
    body: Body,
    density_field: Callable[[np.ndarray], float],
    n_samples: int = 10000,
    *,
    _sdf_resolution: int = 32,
    rng: np.random.Generator | None = None,
) -> InertiaResult:
    """Compute the density-weighted inertia tensor of *body* about its
    mass centroid.

    Parameters
    ----------
    body:
        A closed (watertight) :class:`~kerf_cad_core.geom.brep.Body`.
    density_field:
        Callable ``ρ(point: ndarray) → float``.
    n_samples:
        Number of Monte Carlo candidate samples.  Default 10 000 (higher than
        centroid because the inertia tensor needs more moment accuracy).
    _sdf_resolution:
        SDF grid resolution for point-in-body tests (default 32).
    rng:
        Optional numpy Generator for reproducible results.

    Returns
    -------
    InertiaResult
        centroid, total_mass, inertia_tensor (3×3), samples_used.

    Notes
    -----
    The inertia tensor is computed about the mass centroid C::

        I_ij = Σ_k  ρ_k · (‖r_k‖² δ_ij − r_k_i · r_k_j) · (V_bbox / n_samples)

    where r_k = p_k − C (position relative to centroid).  The diagonal
    I_xx, I_yy, I_zz are the principal moments; off-diagonals are the
    products of inertia (which vanish for symmetric density distributions).
    """
    if rng is None:
        rng = np.random.default_rng()

    sdf, lo, hi, bbox_volume = _build_point_in_body(body, _sdf_resolution)
    span = hi - lo

    pts = lo + rng.random((n_samples, 3)) * span
    sdf_vals = np.array([sdf_sample(sdf, pts[i]) for i in range(n_samples)])
    inside = sdf_vals <= 0.0
    pts_in = pts[inside]
    n_in = len(pts_in)

    if n_in == 0:
        return InertiaResult(
            centroid=np.zeros(3),
            total_mass=0.0,
            inertia_tensor=np.zeros((3, 3)),
            samples_used=0,
        )

    rho = np.array([float(density_field(pts_in[i])) for i in range(n_in)])
    rho = np.maximum(rho, 0.0)
    rho_sum = float(rho.sum())

    if rho_sum < 1e-30:
        return InertiaResult(
            centroid=np.zeros(3),
            total_mass=0.0,
            inertia_tensor=np.zeros((3, 3)),
            samples_used=n_in,
        )

    # Centroid
    centroid = (rho[:, np.newaxis] * pts_in).sum(axis=0) / rho_sum
    total_mass = bbox_volume * rho_sum / n_samples

    # Inertia tensor about centroid
    # r = p - C for each sample
    r = pts_in - centroid  # (n_in, 3)
    r2 = (r * r).sum(axis=1)  # ‖r‖², shape (n_in,)

    # I = Σ ρ_k ( ‖r_k‖² 1 − r_k ⊗ r_k ) * (V_bbox / n_samples)
    # accumulate as weighted sum
    w = rho  # (n_in,)
    # Diagonal: I_xx = Σ ρ (y²+z²), I_yy = Σ ρ (x²+z²), I_zz = Σ ρ (x²+y²)
    scale = bbox_volume / n_samples
    I = np.zeros((3, 3))
    for i in range(3):
        for j in range(3):
            if i == j:
                I[i, j] = float(np.dot(w, r2 - r[:, i] ** 2)) * scale
            else:
                I[i, j] = float(-np.dot(w, r[:, i] * r[:, j])) * scale

    return InertiaResult(
        centroid=centroid,
        total_mass=total_mass,
        inertia_tensor=I,
        samples_used=n_in,
    )


# ---------------------------------------------------------------------------
# Public: named density field patterns (functionally graded materials / FDM)
# ---------------------------------------------------------------------------

def functionally_graded_centroid(
    body: Body,
    density_func_kind: Literal["linear_z", "shell_dense", "radial"] = "linear_z",
    *,
    # linear_z params
    rho_0: float = 1.0,
    alpha: float = 1.0,
    # shell_dense params
    shell_thickness: float | None = None,  # auto-set if None
    rho_shell: float = 2.0,
    rho_core: float = 0.5,
    # radial params
    rho_max: float = 1.0,
    R: float | None = None,  # auto-set if None
    # Monte Carlo
    n_samples: int = 1000,
    rng: np.random.Generator | None = None,
) -> CentroidResult:
    """Compute the mass-weighted centroid for common functionally-graded
    material (FGM) density distributions.

    Parameters
    ----------
    body:
        A closed (watertight) B-rep Body.
    density_func_kind:
        One of:

        ``'linear_z'``
            Linearly increasing density along z:
            ``ρ(z) = ρ_0 · (1 + α · (z − z_lo) / L)``
            where L is the body z-extent and z_lo is the bottom.
            Emulates density-graded multi-material or FDM variable-infill.
        ``'shell_dense'``
            Dense shell, light interior (3-D-printed shell + sparse infill):
            Points within *shell_thickness* of the surface have density
            *rho_shell*; interior points have *rho_core*.
        ``'radial'``
            Radially decaying density from the body centroid:
            ``ρ(r) = ρ_max / (1 + r/R)²``
            (soft-inner / hard-outer or vice-versa depending on parameters).

    rho_0:
        Base density for ``linear_z`` (default 1.0).
    alpha:
        Gradient coefficient for ``linear_z``.  ``alpha=1`` gives density
        range ``[ρ_0, 2·ρ_0]``; ``alpha=-1`` gives ``[2·ρ_0, ρ_0]``.
    shell_thickness:
        Shell thickness for ``shell_dense``.  Defaults to 10% of the body
        bounding-box diagonal.
    rho_shell, rho_core:
        Density of the shell and core regions for ``shell_dense``.
    rho_max:
        Peak density for ``radial`` (at the centroid).
    R:
        Decay length for ``radial``.  Defaults to 50% of the bounding-box
        half-diagonal.
    n_samples:
        Monte Carlo samples (default 1000).
    rng:
        Optional numpy Generator.

    Returns
    -------
    CentroidResult
    """
    if rng is None:
        rng = np.random.default_rng()

    sdf, lo, hi, bbox_volume = _build_point_in_body(body)
    span = hi - lo
    diag = float(np.linalg.norm(span))

    if density_func_kind == "linear_z":
        z_lo = float(lo[2])
        L = float(span[2]) if float(span[2]) > 1e-14 else 1.0

        def density_field(p: np.ndarray) -> float:
            return float(rho_0 * (1.0 + alpha * (p[2] - z_lo) / L))

    elif density_func_kind == "shell_dense":
        t = shell_thickness if shell_thickness is not None else 0.10 * diag

        def density_field(p: np.ndarray) -> float:
            d = sdf_sample(sdf, p)  # negative inside, positive outside
            # d in (-t, 0] → within t of surface → shell
            if d >= -t:
                return float(rho_shell)
            return float(rho_core)

    elif density_func_kind == "radial":
        # Body geometric centroid (uniform density) as the radial origin
        geo_centroid = (lo + hi) / 2.0
        R_val = R if R is not None else 0.5 * diag / 2.0

        def density_field(p: np.ndarray) -> float:
            r_dist = float(np.linalg.norm(p - geo_centroid))
            return float(rho_max / (1.0 + r_dist / max(R_val, 1e-14)) ** 2)

    else:
        raise ValueError(
            f"Unknown density_func_kind {density_func_kind!r}. "
            "Choose from 'linear_z', 'shell_dense', 'radial'."
        )

    return compute_centroid_density_field(
        body,
        density_field,
        n_samples=n_samples,
        rng=rng,
    )
