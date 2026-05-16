"""
kerf_cad_core.cmm — CMM / coordinate-metrology inspection planning.

Pure-Python module providing:
  • Least-squares geometric fitting from measured 3D points (line, plane,
    circle, sphere, cylinder) with residuals and form-error reporting.
  • Datum-reference-frame (DRF) alignment: 3-2-1 and best-fit with rigid
    6-DOF transform output.
  • GD&T evaluation directly from measured point clouds (flatness, circularity,
    cylindricity, perpendicularity / parallelism / angularity to a datum,
    position with MMC bonus tolerance, surface profile).
  • Measurement uncertainty per GUM (Guide to the Expression of Uncertainty
    in Measurement): combine Type-A and Type-B uncertainties, apply k-factor.
  • Probe-radius compensation (vector offset along surface normal).
  • Sampling-point recommendation based on Nyquist criterion on harmonic form.
  • Gauge R&R analysis: ANOVA method and Average-Range method, %study variation,
    number of distinct categories (ndc).
  • Process capability: Cpk and Ppk from a sample of measurements.

No external dependencies; all linear-algebra is hand-rolled (small dense
matrices via nested lists / tuples).  Out-of-tolerance and R&R-not-capable
conditions are flagged in the returned dict under ``warnings``; functions
never raise.

Author: imranparuk
"""

from kerf_cad_core.cmm.inspect import (
    fit_line,
    fit_plane,
    fit_circle,
    fit_sphere,
    fit_cylinder,
    align_321,
    align_bestfit,
    eval_flatness,
    eval_circularity,
    eval_cylindricity,
    eval_perpendicularity,
    eval_parallelism,
    eval_angularity,
    eval_position,
    eval_profile,
    gum_uncertainty,
    probe_compensate,
    recommend_samples,
    gauge_rr_anova,
    gauge_rr_avgrange,
    process_capability,
)

__all__ = [
    "fit_line",
    "fit_plane",
    "fit_circle",
    "fit_sphere",
    "fit_cylinder",
    "align_321",
    "align_bestfit",
    "eval_flatness",
    "eval_circularity",
    "eval_cylindricity",
    "eval_perpendicularity",
    "eval_parallelism",
    "eval_angularity",
    "eval_position",
    "eval_profile",
    "gum_uncertainty",
    "probe_compensate",
    "recommend_samples",
    "gauge_rr_anova",
    "gauge_rr_avgrange",
    "process_capability",
]
