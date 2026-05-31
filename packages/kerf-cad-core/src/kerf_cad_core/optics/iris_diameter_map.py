"""
kerf_cad_core.optics.iris_diameter_map — Iris (Aperture Stop) Diameter Map.

Given a target f-number and entrance-pupil position for a sequential lens
system, compute the required iris (aperture stop) physical diameter and verify
that the marginal ray does not clip any other surface's clear aperture.

Theory (Welford "Aberrations of Optical Systems" §3.4 / Smith "Modern
Optical Engineering" §6):

    D_iris = EFL / f#                       (paraxial, infinity-conjugate)

The marginal ray height at each surface is obtained by tracing a paraxial
marginal ray with h_0 = D_iris/2 at the iris (aperture stop) surface and
u_0 = 0 (collimated from infinity).  For a stop at the front surface this is
the canonical h=D/2, u=0 input.  For a stop at an interior surface the ray
height at the stop is set to h=D/2, and the system is propagated forward
(surfaces after the stop) and backward (surfaces before the stop, reversed).

Clipping flag:
    A surface is flagged as potentially clipping when the marginal-ray height
    exceeds 0.95 × clear_aperture_radius.  This 0.95 factor provides a 5%
    margin for real-world alignment tolerances.

Honest caveats (required by task spec):
    * Paraxial (first-order) marginal-ray trace only.
    * D = EFL/f# is the infinity-conjugate formula; for finite-conjugate
      systems use the working-f-number formula (Smith MOE §4.5).
    * Aspheric surfaces: paraxial trace ignores higher-order sag; for
      production design use exact ray analysis (Welford §5 / CODE V / Zemax).
    * Clear aperture supplied by the caller; not inferred from surface geometry.

Units: lengths in mm; dimensionless f-numbers and ratios.

References
----------
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §3.4.
Smith, W.J. — "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008, §6.
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017, §6.4.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False,
           finite: bool = True) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if finite and not math.isfinite(v):
        return f"{name} must be finite"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    return None


def _validate_surface(s: Any, idx: int) -> str | None:
    if not isinstance(s, dict):
        return f"surface[{idx}] must be a dict"
    for fld in ("c", "t", "n"):
        if fld not in s:
            return f"surface[{idx}] missing required field '{fld}'"
        err = _guard(f"surface[{idx}].{fld}", s[fld])
        if err:
            return err
    if float(s["n"]) < 1.0:
        return f"surface[{idx}].n must be >= 1.0"
    return None


# ---------------------------------------------------------------------------
# Paraxial trace helpers (Welford 1986 §3.3, nu-form)
# ---------------------------------------------------------------------------

def _paraxial_refract(h: float, u: float, n: float,
                      n_prime: float, c: float) -> float:
    """Paraxial refraction: n'u' = nu - hc(n'-n). Returns u'."""
    nu_prime = n * u - h * c * (n_prime - n)
    return nu_prime / n_prime


def _paraxial_transfer(h: float, u_prime: float, t: float) -> float:
    """Transfer: h_{j+1} = h_j + t * u'_j."""
    return h + t * u_prime


def _trace_forward(surfaces: list[dict], h0: float, u0: float,
                   n_start: float) -> list[tuple[float, float, float]]:
    """
    Trace paraxial marginal ray forward through all surfaces.

    Returns list of (h, u_in, n_in) at each surface vertex.
    h is the ray height arriving AT the surface, u_in is angle BEFORE refraction,
    n_in is index BEFORE refraction at this surface.
    """
    h, u, n = h0, u0, n_start
    log = []
    for s in surfaces:
        c = float(s["c"])
        t = float(s["t"])
        n_prime = float(s["n"])
        log.append((h, u, n))          # height arriving, angle before refraction, index before
        u = _paraxial_refract(h, u, n, n_prime, c)
        h = _paraxial_transfer(h, u, t)
        n = n_prime
    return log


def _compute_efl_from_trace(surfaces: list[dict],
                             n_object: float = 1.0) -> float:
    """
    Compute EFL via marginal ray h=1, u=0 (collimated input from infinity).
    EFL = -1 / u_final  (for h_in=1; Welford §3.5).
    Returns math.inf for afocal systems.
    """
    h, u, n = 1.0, 0.0, n_object
    for s in surfaces:
        c = float(s["c"])
        t = float(s["t"])
        n_prime = float(s["n"])
        u = _paraxial_refract(h, u, n, n_prime, c)
        h = _paraxial_transfer(h, u, t)
        n = n_prime
    if abs(u) < 1e-18:
        return math.inf
    return -1.0 / u


# ---------------------------------------------------------------------------
# Clipping threshold
# ---------------------------------------------------------------------------

_CLIP_THRESHOLD = 0.95   # marginal_ray_height > 0.95 * CA_radius → potential clip


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class IrisMapSpec:
    """
    Input specification for iris diameter computation.

    Attributes
    ----------
    lens_system_dict : dict
        Optical system descriptor.  Required key:
          surfaces : list[dict]  — each surface has c (mm^-1), t (mm), n,
                                   optionally k (conic).
        Optional keys:
          stop_surface_index : int   — 0-based index of the aperture-stop
                                       surface (default 0 = front surface).
          clear_apertures_mm : list[float] — per-surface clear aperture
                                             DIAMETER (mm).  Length must
                                             equal number of surfaces.
                                             Omit for "no physical rim" check.
          n_object : float — object-space refractive index (default 1.0).
    target_f_number : float
        Target f-number N = EFL / D.  Must be > 0.
    target_efl_mm : float | None
        Override effective focal length (mm).  If None the EFL is computed
        from the surface data via the canonical marginal-ray trace.
    """

    lens_system_dict: dict
    target_f_number: float
    target_efl_mm: float | None = None


@dataclass
class IrisDiameterReport:
    """
    Output from compute_iris_diameter.

    Attributes
    ----------
    iris_diameter_mm : float
        Required iris physical diameter D = EFL / f# (paraxial, mm).
    effective_f_number : float
        Actual f-number EFL / iris_diameter_mm (equals target_f_number
        when EFL is not overridden; differs if target_efl_mm is supplied).
    efl_mm : float
        Effective focal length used in the calculation (mm).
    surface_clearance_check : list[dict]
        One entry per surface:
          surface_idx       : int   — 0-based surface index
          clear_aperture_mm : float — physical CA diameter (mm; NaN if not supplied)
          marginal_ray_height_mm : float — |h| at this surface (mm)
          clearance_ratio   : float — CA_radius / marginal_ray_height
                              > 1 → clears; < 1 → clips; NaN if no CA given.
    clipped : bool
        True if ANY surface has marginal_ray_height > 0.95 × CA_radius
        (i.e., clearance_ratio < 1/0.95 ≈ 1.053).
    honest_caveat : str
        Plain-English limitations of the paraxial analysis.
    """

    iris_diameter_mm: float
    effective_f_number: float
    efl_mm: float
    surface_clearance_check: list[dict] = field(default_factory=list)
    clipped: bool = False
    honest_caveat: str = field(default="", repr=False)

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "iris_diameter_mm": self.iris_diameter_mm,
            "effective_f_number": self.effective_f_number,
            "efl_mm": self.efl_mm,
            "surface_clearance_check": self.surface_clearance_check,
            "clipped": self.clipped,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Honest caveat string
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Paraxial (first-order) marginal-ray trace only (Welford §3.4).  "
    "D = EFL/f# is the infinity-conjugate formula; for finite-conjugate "
    "systems the working f-number N_w = N*(1+|m|) must be used (Smith MOE "
    "§4.5).  Aspheric surface higher-order sag terms are ignored in the "
    "paraxial trace; for production design use exact skew-ray analysis "
    "(Welford §5, CODE V or Zemax OpticStudio).  Clear apertures are "
    "caller-supplied; this module does not infer physical lens rim radii "
    "from surface data.  Clipping threshold is 0.95 × CA_radius; small "
    "alignment tolerances are not modelled.  Surface tilt/decenter not "
    "supported (centred sequential systems only)."
)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_iris_diameter(spec: IrisMapSpec) -> IrisDiameterReport | dict:
    """
    Compute the required iris physical diameter and verify surface clearances.

    Algorithm (Welford 1986 §3.4 / Smith MOE §6):

    1.  Validate inputs.
    2.  Compute EFL via canonical marginal-ray trace (h=1, u=0) unless
        target_efl_mm is supplied.
    3.  D_iris = EFL / f#  (paraxial infinity-conjugate).
    4.  Trace a paraxial marginal ray with h = D_iris/2 at the aperture
        stop, u = 0 (collimated from infinity):
          * Surfaces AFTER the stop: forward trace.
          * Surfaces BEFORE the stop: backward trace through a reversed
            sub-system (flip signs, reverse order).
    5.  For each surface with a supplied clear aperture CA_radius (mm):
          clearance_ratio = CA_radius / |h_at_surface|
          clipped if |h| > 0.95 * CA_radius.

    Parameters
    ----------
    spec : IrisMapSpec

    Returns
    -------
    IrisDiameterReport on success, or dict {ok: False, reason: ...} on error.
    """
    lsd = spec.lens_system_dict
    if not isinstance(lsd, dict):
        return _err("lens_system_dict must be a dict")

    surfaces = lsd.get("surfaces")
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("lens_system_dict.surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    n_surfaces = len(surfaces)

    # target_f_number
    fno = spec.target_f_number
    e = _guard("target_f_number", fno, positive=True)
    if e:
        return _err(e)
    fno = float(fno)

    # optional target_efl_mm
    if spec.target_efl_mm is not None:
        e = _guard("target_efl_mm", spec.target_efl_mm, positive=True)
        if e:
            return _err(e)
        efl = float(spec.target_efl_mm)
    else:
        n_object = float(lsd.get("n_object", 1.0))
        if n_object < 1.0:
            return _err("lens_system_dict.n_object must be >= 1.0")
        efl = _compute_efl_from_trace(surfaces, n_object=n_object)
        if not math.isfinite(efl) or efl <= 0.0:
            return _err(
                f"Computed EFL is {efl:.4g} mm (afocal or negative lens); "
                "supply target_efl_mm explicitly for non-convergent systems."
            )

    # Iris diameter
    iris_d = efl / fno          # D = EFL / f#
    effective_fno = efl / iris_d

    # stop surface index
    stop_idx = int(lsd.get("stop_surface_index", 0))
    if not (0 <= stop_idx < n_surfaces):
        return _err(
            f"stop_surface_index={stop_idx} out of range [0, {n_surfaces - 1}]"
        )

    # clear apertures (diameters → radii)
    ca_list_raw = lsd.get("clear_apertures_mm")
    if ca_list_raw is not None:
        if len(ca_list_raw) != n_surfaces:
            return _err(
                f"clear_apertures_mm length {len(ca_list_raw)} != "
                f"n_surfaces {n_surfaces}"
            )
        ca_radii = [float(v) / 2.0 for v in ca_list_raw]
    else:
        ca_radii = [math.nan] * n_surfaces

    # -----------------------------------------------------------------------
    # Marginal-ray trace
    # -----------------------------------------------------------------------
    # Strategy: set h=D/2, u=0 at the stop surface.  Trace forward for
    # surfaces at and after the stop; trace backward for surfaces before.
    #
    # Forward trace (from stop → last surface):
    #   h_stop = D/2, u_stop = 0, n_in = n_object (if stop at front) or
    #   n of medium before stop surface.

    h_stop = iris_d / 2.0

    # Determine n_in at stop surface:
    n_object = float(lsd.get("n_object", 1.0))
    if stop_idx == 0:
        n_before_stop = n_object
    else:
        n_before_stop = float(surfaces[stop_idx - 1]["n"])

    # Heights at each surface (indexed 0..n_surfaces-1)
    h_at_surface: list[float] = [0.0] * n_surfaces

    # Forward pass: stop surface → last surface
    h_fwd, u_fwd, n_fwd = h_stop, 0.0, n_before_stop
    for idx in range(stop_idx, n_surfaces):
        s = surfaces[idx]
        c = float(s["c"])
        t = float(s["t"])
        n_prime = float(s["n"])
        h_at_surface[idx] = h_fwd
        u_fwd = _paraxial_refract(h_fwd, u_fwd, n_fwd, n_prime, c)
        h_fwd = _paraxial_transfer(h_fwd, u_fwd, t)
        n_fwd = n_prime

    # Backward pass: surfaces before the stop (if any)
    # We reverse the sub-system: flip curvature signs, reverse order, fix n values.
    if stop_idx > 0:
        # Sub-system: surfaces[0..stop_idx-1] in forward order.
        # We image the stop backward through this reversed sub-system.
        # The stop is the "object" at the right end of the sub-system.
        # n_sequence in forward order: n_object, n[0], n[1], ..., n[stop_idx-1]
        n_seq_fwd = [n_object] + [float(surfaces[k]["n"]) for k in range(stop_idx)]
        # Reversed: surface order is stop_idx-1 down to 0.
        # In the reversed trace, the "object" medium is n_seq_fwd[stop_idx]
        # = n_before_stop.

        # Build reversed sub-system dicts for forward-paraxial trace
        rev_surfs = []
        for i in range(stop_idx):
            orig_idx = stop_idx - 1 - i
            # thickness in reversed system = thickness of previous original surface
            if orig_idx > 0:
                t_rev = float(surfaces[orig_idx - 1]["t"])
            else:
                t_rev = 0.0
            rev_surfs.append({
                "c": -float(surfaces[orig_idx]["c"]),
                "t": t_rev,
                "n": n_seq_fwd[orig_idx],   # medium after reversed refraction
                "k": float(surfaces[orig_idx].get("k", 0.0)),
            })
        # The last reversed surface should have t=0
        rev_surfs[-1]["t"] = 0.0

        h_rev, u_rev, n_rev = h_stop, 0.0, n_before_stop
        for i, rev_s in enumerate(rev_surfs):
            c = float(rev_s["c"])
            t = float(rev_s["t"])
            n_prime = float(rev_s["n"])
            # Map back to original surface index
            orig_idx = stop_idx - 1 - i
            h_at_surface[orig_idx] = h_rev
            u_rev = _paraxial_refract(h_rev, u_rev, n_rev, n_prime, c)
            h_rev = _paraxial_transfer(h_rev, u_rev, t)
            n_rev = n_prime

    # -----------------------------------------------------------------------
    # Clearance check
    # -----------------------------------------------------------------------
    clearance_records: list[dict] = []
    any_clipped = False

    for idx in range(n_surfaces):
        h_abs = abs(h_at_surface[idx])
        ca_r = ca_radii[idx]

        if math.isnan(ca_r):
            ratio = math.nan
            flagged = False
        else:
            if h_abs < 1e-15:
                ratio = math.inf
                flagged = False
            else:
                ratio = ca_r / h_abs
                flagged = h_abs > _CLIP_THRESHOLD * ca_r

        if flagged:
            any_clipped = True

        clearance_records.append({
            "surface_idx": idx,
            "clear_aperture_mm": (ca_r * 2.0) if not math.isnan(ca_r) else math.nan,
            "marginal_ray_height_mm": h_abs,
            "clearance_ratio": ratio,
            "flagged": flagged,
        })

    return IrisDiameterReport(
        iris_diameter_mm=iris_d,
        effective_f_number=effective_fno,
        efl_mm=efl,
        surface_clearance_check=clearance_records,
        clipped=any_clipped,
        honest_caveat=_HONEST_CAVEAT,
    )
