"""
kerf_cad_core.optics.focal_depth_field — Depth-of-Field and Hyperfocal Distance.

Implements the standard photographic thin-lens depth-of-field model:

  Hyperfocal distance:
      H = f² / (N · c) + f                      (Greenleaf §3.2 / Hecht §6.4)

  Near limit of acceptable focus:
      D_near = D · (H - f) / (H + D - 2f)

  Far limit of acceptable focus:
      D_far  = D · (H - f) / (H - D)            [D_far = ∞ when D ≥ H]

  Total depth of field:
      DoF = D_far - D_near                       [∞ when D ≥ H]

  Behind-focus fraction:
      frac_behind = (D_far - D) / DoF            [NaN when DoF = ∞]

  Infinity-focus check:
      At D = H, D_far → ∞  →  infinity_focus_at_hyperfocal = True.

Units: millimetres throughout (focal_length_mm, focus_distance_mm, etc.).

Honest caveat:
  This model is purely geometric (ray-optics).  It does NOT add the
  diffraction-limited Airy-disk blur to the geometric CoC at small
  apertures (f/# ≳ f/16 for visible light, where 1.22·λ·N approaches
  the 35mm-FF CoC of 0.03 mm).  For applications requiring a combined
  blur circle the caller should compute:
      c_eff = sqrt(c_geometric² + c_airy²)
  and re-call compute_depth_of_field with c_eff.

References
----------
Hecht, E. — "Optics", 5th ed. (2017), §6.4 (Depth of Field).
Greenleaf, A.R. — "Photographic Optics" (1950), §3 (Depth of Focus).
Kingslake, R. — "Lens Design Fundamentals" (1978), §4.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LensFocusSpec:
    """
    Input specification for a thin-lens imaging system.

    Attributes
    ----------
    focal_length_mm : float
        Focal length of the lens (mm).  Must be > 0.
    f_number : float
        Aperture f-number (f/#).  Must be > 0.
    focus_distance_mm : float
        Distance from the lens to the plane of sharpest focus (mm).
        Must be > focal_length_mm (real, in-front-of-lens focus).
    circle_of_confusion_mm : float
        Maximum acceptable blur-spot diameter on the image plane (mm).
        Default 0.03 mm — the 35mm full-frame standard (diagonal 43 mm,
        1/1400 of diagonal, Greenleaf §3; also Leica CoC convention).
        APS-C: 0.019 mm; MFT: 0.015 mm; medium-format 645: 0.045 mm.
    """

    focal_length_mm: float
    f_number: float
    focus_distance_mm: float
    circle_of_confusion_mm: float = 0.03


@dataclass
class DepthOfFieldReport:
    """
    Output report from compute_depth_of_field.

    Attributes
    ----------
    hyperfocal_distance_mm : float
        H = f²/(N·c) + f.  At focus distance H, everything from H/2 to
        infinity is acceptably sharp.
    near_limit_mm : float
        Nearest distance from the lens that falls within acceptable focus.
    far_limit_mm : float
        Furthest in-focus distance; math.inf when focus distance ≥ H.
    depth_of_field_mm : float
        Total depth of field = far_limit - near_limit; math.inf when far = ∞.
    behind_focus_fraction : float
        Fraction of the (finite) DoF that lies *behind* the focus plane:
        (far - D) / DoF.  NaN when DoF is infinite.
    infinity_focus_at_hyperfocal : bool
        True when the focus distance equals or exceeds the hyperfocal distance
        (i.e., far limit is at infinity).
    honest_caveat : str
        Plain-English limitations string.
    """

    hyperfocal_distance_mm: float
    near_limit_mm: float
    far_limit_mm: float
    depth_of_field_mm: float
    behind_focus_fraction: float
    infinity_focus_at_hyperfocal: bool
    honest_caveat: str = field(default="", repr=False)

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "hyperfocal_distance_mm": self.hyperfocal_distance_mm,
            "near_limit_mm": self.near_limit_mm,
            "far_limit_mm": (
                None if math.isinf(self.far_limit_mm) else self.far_limit_mm
            ),
            "depth_of_field_mm": (
                None if math.isinf(self.depth_of_field_mm) else self.depth_of_field_mm
            ),
            "behind_focus_fraction": (
                None if math.isnan(self.behind_focus_fraction) else self.behind_focus_fraction
            ),
            "infinity_focus_at_hyperfocal": self.infinity_focus_at_hyperfocal,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Geometric thin-lens DoF model only.  Does NOT add diffraction-limited "
    "Airy-disk blur to the geometric CoC.  At small apertures (f/# ≳ f/16 "
    "for visible light) the Airy disk 1.22·λ·N approaches the 35mm-FF CoC "
    "of 0.03 mm, so geometric DoF is slightly optimistic.  For a combined "
    "blur circle use c_eff = sqrt(c_geom² + c_airy²).  "
    "Model also ignores focus breathing, distortion, and field curvature."
)


def compute_depth_of_field(spec: LensFocusSpec) -> DepthOfFieldReport:
    """
    Compute hyperfocal distance, near/far DoF limits, and related metrics.

    Uses the exact photographic DoF formulae (Greenleaf §3 / Hecht §6.4):

        H      = f² / (N · c) + f
        D_near = D · (H - f) / (H + D - 2f)
        D_far  = D · (H - f) / (H - D)    [∞ when D ≥ H]

    Parameters
    ----------
    spec : LensFocusSpec
        Input specification (focal_length_mm, f_number, focus_distance_mm,
        circle_of_confusion_mm).

    Returns
    -------
    DepthOfFieldReport
        All computed values.  Never raises — returns a report with
        near_limit_mm=0 for degenerate geometry (object inside focal length).

    Raises
    ------
    ValueError
        If focal_length_mm, f_number, or circle_of_confusion_mm are
        non-positive, or focus_distance_mm ≤ focal_length_mm.
    """
    f = float(spec.focal_length_mm)
    N = float(spec.f_number)
    c = float(spec.circle_of_confusion_mm)
    D = float(spec.focus_distance_mm)

    if f <= 0.0:
        raise ValueError(f"focal_length_mm must be > 0, got {f}")
    if N <= 0.0:
        raise ValueError(f"f_number must be > 0, got {N}")
    if c <= 0.0:
        raise ValueError(f"circle_of_confusion_mm must be > 0, got {c}")
    if D <= f:
        raise ValueError(
            f"focus_distance_mm ({D}) must be > focal_length_mm ({f})"
        )

    # Hyperfocal distance: H = f²/(N·c) + f
    H = (f * f) / (N * c) + f

    # Near limit: D_near = D·(H-f) / (H + D - 2f)
    near_denom = H + D - 2.0 * f
    if near_denom <= 0.0:
        # Extremely short focus relative to hyperfocal — near limit at lens
        near = 0.0
    else:
        near = D * (H - f) / near_denom

    # Far limit: D_far = D·(H-f) / (H - D)  [∞ when D ≥ H]
    far_denom = H - D
    if far_denom <= 0.0:
        # Focus distance at or beyond hyperfocal → far limit at ∞
        far = math.inf
    else:
        far = D * (H - f) / far_denom

    infinity_at_hyp = math.isinf(far)

    dof = math.inf if math.isinf(far) else (far - near)

    if math.isinf(dof) or dof == 0.0:
        behind_frac = math.nan
    else:
        behind_frac = (far - D) / dof

    return DepthOfFieldReport(
        hyperfocal_distance_mm=H,
        near_limit_mm=near,
        far_limit_mm=far,
        depth_of_field_mm=dof,
        behind_focus_fraction=behind_frac,
        infinity_focus_at_hyperfocal=infinity_at_hyp,
        honest_caveat=_HONEST_CAVEAT,
    )
