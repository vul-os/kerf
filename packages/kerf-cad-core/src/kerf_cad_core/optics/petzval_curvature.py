"""
kerf_cad_core.optics.petzval_curvature — Petzval field curvature for sequential
optical systems.

Public API
----------
compute_petzval_curvature(lens_system_dict) -> PetzvalReport
    Compute the Petzval sum P = 1/R_P and related field-flatness metrics for a
    sequential lens system described by a list of refracting surfaces.

Theory (Hecht "Optics" 5e §6.3.2 / Born & Wolf "Principles of Optics" §4.5)
---------------------------------------------------------------------------
The Petzval field-curvature sum for a sequential system of k refracting surfaces
is:

    P = Σ_i  (n_after_i − n_before_i) / (n_before_i · n_after_i · R_i)

which simplifies for a thin lens in air (n_before=1, n_after=n_glass) to:

    P ≈ (n−1) · (1/R1 − 1/R2) / n    [Hecht eq. 6.69]

For a single thin BK7 lens (n=1.5168, R1=+50 mm, R2=−50 mm) this gives
P ≈ 0.01366 mm⁻¹, i.e. R_P ≈ 73.2 mm  (Petzval radius).

The *flat-field* (Petzval) condition is P = 0, achievable in doublets / triplets
with appropriate bending and glass choice.

Input surface convention
-----------------------
Each surface dict must contain:
  radius_mm      : float  Radius of curvature (mm). Use math.inf (or 1e18) for a
                           planar surface. Sign: R > 0 → centre of curvature to right.
  n_index_before : float  Refractive index of the medium before this surface (>= 1.0).
  n_index_after  : float  Refractive index of the medium after this surface (>= 1.0).

Per-surface contribution:
    contrib_i = (n_after - n_before) / (n_before * n_after * R_i)

Planar surfaces (|R| > 1e15 mm) contribute 0 to P.

Field-flatness score
--------------------
    score = 1 / (1 + |P| * 100)   ∈ (0, 1]

This maps P = 0 → score = 1.0 (perfectly flat Petzval), with a natural
decay that reaches ≈ 0.5 at |P| = 0.01 mm⁻¹ (R_P ≈ 100 mm, noticeable curvature).

HONEST CAVEATS
--------------
* The Petzval sum is a *paraxial* (third-order) quantity and does not capture
  astigmatism, which shifts the tangential and sagittal focal surfaces relative to
  the Petzval sphere (Born & Wolf §4.5.1). The *actual* field curvature seen in a
  system with residual astigmatism differs from 1/R_P.
* P = 0 guarantees a flat Petzval surface but NOT zero astigmatism; a system can
  have P = 0 yet large S_III (Hecht §6.3.2).
* This module does not account for thick-lens or pupil-aberration corrections to the
  Petzval sum (Smith, "Modern Optical Engineering" §4.4).
* Stop-shift invariance: the Petzval sum is *independent* of the aperture stop
  position (Born & Wolf §4.5, footnote 3).

References
----------
Hecht, E. — "Optics", 5th ed. (2017), §6.3.2 (Field Curvature & Astigmatism).
Born, M. & Wolf, E. — "Principles of Optics", 7th ed. (1999), §4.5.
Smith, W.J. — "Modern Optical Engineering", 4th ed. (2008), §4.4.

Units: all lengths in mm throughout.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Internal validation helpers
# ---------------------------------------------------------------------------

_PLANO_THRESHOLD = 1e15  # |R| > this ⟹ treat as flat (contributes 0)


def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard_number(name: str, value: Any, *, positive: bool = False) -> str | None:
    """Return an error string if *value* is not a valid (optionally positive) finite number."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite (got {v}); use 1e18 for a planar surface"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    return None


def _validate_surface(s: Any, idx: int) -> str | None:
    if not isinstance(s, dict):
        return f"surface[{idx}] must be a dict"
    for fld in ("radius_mm", "n_index_before", "n_index_after"):
        if fld not in s:
            return f"surface[{idx}] missing required field '{fld}'"
    err = _guard_number(f"surface[{idx}].radius_mm", s["radius_mm"])
    if err:
        return err
    for fld in ("n_index_before", "n_index_after"):
        err = _guard_number(f"surface[{idx}].{fld}", s[fld], positive=True)
        if err:
            return err
        if float(s[fld]) < 1.0:
            return f"surface[{idx}].{fld} must be >= 1.0, got {s[fld]}"
    return None


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PetzvalReport:
    """
    Petzval field-curvature analysis for a sequential optical system.

    Attributes
    ----------
    petzval_sum : float
        P = Σ (n_after − n_before) / (n_before · n_after · R_i)  [mm⁻¹]
        A.k.a. 1/R_P; the curvature of the Petzval sphere.
        P = 0 ⟹ flat Petzval field.
    petzval_radius_mm : float
        R_P = 1/P  (mm). math.inf when P = 0 (perfectly flat).
        Negative R_P indicates a concave Petzval surface (less common).
    field_flatness_score : float
        Scalar quality score ∈ (0, 1].  1.0 = flat field, decays toward 0
        as |P| increases.  Defined as 1 / (1 + |P| * 100).
    per_surface_contributions : list[dict]
        Per-surface breakdown.  Each dict has:
          surface_index  : int
          radius_mm      : float
          n_before       : float
          n_after        : float
          contribution   : float  (n_after−n_before) / (n_before·n_after·R)
          is_plano       : bool   True if |R| > 1e15 mm
    honest_caveat : str
        Human-readable scope disclaimer.
    """

    petzval_sum: float = 0.0
    petzval_radius_mm: float = math.inf
    field_flatness_score: float = 1.0
    per_surface_contributions: list = field(default_factory=list)
    honest_caveat: str = (
        "Petzval sum is a paraxial (third-order) quantity. "
        "It does not capture astigmatism: the tangential and sagittal focal surfaces "
        "differ from the Petzval sphere by the astigmatic interval (S_III term). "
        "P=0 guarantees a flat Petzval surface but NOT zero astigmatism (Hecht §6.3.2). "
        "Thick-lens and pupil-aberration corrections to P are not modelled "
        "(Smith 'Modern Optical Engineering' §4.4)."
    )

    def to_dict(self) -> dict:
        rp = self.petzval_radius_mm
        return {
            "ok": True,
            "petzval_sum_mm_inv": self.petzval_sum,
            "petzval_radius_mm": rp if math.isfinite(rp) else None,
            "field_flatness_score": self.field_flatness_score,
            "per_surface_contributions": self.per_surface_contributions,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_petzval_curvature(lens_system_dict: dict) -> PetzvalReport | dict:
    """
    Compute the Petzval field curvature for a sequential optical system.

    Parameters
    ----------
    lens_system_dict : dict
        Must contain key ``"surfaces"`` — a list of surface dicts, each with:
          * ``radius_mm``      : float  (use 1e18 for plano; finite non-zero)
          * ``n_index_before`` : float  (refractive index before this surface, ≥ 1.0)
          * ``n_index_after``  : float  (refractive index after this surface, ≥ 1.0)

    Returns
    -------
    PetzvalReport  on success, or a ``{"ok": False, "reason": ...}`` dict on error.

    Examples
    --------
    Single thin BK7 lens (R1=+50, R2=−50, n=1.5168):

    >>> sys_dict = {
    ...     "surfaces": [
    ...         {"radius_mm": 50.0,  "n_index_before": 1.0,    "n_index_after": 1.5168},
    ...         {"radius_mm": -50.0, "n_index_before": 1.5168, "n_index_after": 1.0},
    ...     ]
    ... }
    >>> r = compute_petzval_curvature(sys_dict)
    >>> abs(r.petzval_sum - 0.013657) < 1e-4
    True
    >>> abs(r.petzval_radius_mm - 73.2) < 1.0
    True
    """
    if not isinstance(lens_system_dict, dict):
        return _err("lens_system_dict must be a dict")

    surfaces = lens_system_dict.get("surfaces")
    if surfaces is None:
        return _err("lens_system_dict must contain key 'surfaces'")
    if not isinstance(surfaces, list):
        return _err("'surfaces' must be a list")
    if len(surfaces) == 0:
        return _err("'surfaces' must contain at least one surface")

    for i, s in enumerate(surfaces):
        err = _validate_surface(s, i)
        if err:
            return _err(err)

    petzval_sum = 0.0
    per_surface: list[dict] = []

    for i, s in enumerate(surfaces):
        R = float(s["radius_mm"])
        n_before = float(s["n_index_before"])
        n_after = float(s["n_index_after"])
        is_plano = abs(R) >= _PLANO_THRESHOLD

        if is_plano:
            contrib = 0.0
        else:
            # Petzval contribution: (n_after - n_before) / (n_before * n_after * R)
            delta_n = n_after - n_before
            contrib = delta_n / (n_before * n_after * R)

        petzval_sum += contrib
        per_surface.append({
            "surface_index": i,
            "radius_mm": R,
            "n_before": n_before,
            "n_after": n_after,
            "contribution": contrib,
            "is_plano": is_plano,
        })

    # Petzval radius
    if abs(petzval_sum) < 1e-30:
        petzval_radius_mm = math.inf
    else:
        petzval_radius_mm = 1.0 / petzval_sum

    # Field-flatness score: 1/(1 + |P|*100)
    # Maps P=0 → 1.0; |P|=0.01 → 0.5; |P|=0.1 → 0.091
    field_flatness_score = 1.0 / (1.0 + abs(petzval_sum) * 100.0)

    return PetzvalReport(
        petzval_sum=petzval_sum,
        petzval_radius_mm=petzval_radius_mm,
        field_flatness_score=field_flatness_score,
        per_surface_contributions=per_surface,
    )
