"""
kerf_cad_core.seismic — ASCE 7 seismic equivalent lateral force & response.

Pure-Python module; no OCC dependency.  Distinct from vibration/ (mechanical
rotating machinery), geotech/ (soil behaviour), and struct/ (member sizing).

Submodules
----------
elf       — design spectral accelerations (SDS/SD1), approximate period,
            design response spectrum Sa(T), seismic response coefficient Cs,
            base shear V, vertical force distribution Fx, storey shear &
            overturning, drift & stability coefficient θ, SDOF spectral
            displacement, R/Ω0/Cd application.
rsa       — ASCE 7-22 §12.9 Response-Spectrum Analysis (RSA) + Newmark-β
            time-history integration (SRSS, CQC, SDOF, MDOF).
tools     — LLM tool wrappers for ELF functions.
rsa_tools — LLM tool wrappers for RSA & time-history functions.

Public API (re-exported for convenience)
-----------------------------------------
    from kerf_cad_core.seismic import (
        site_coefficients,
        design_spectrum,
        approximate_period,
        seismic_response_coefficient,
        base_shear,
        vertical_distribution,
        story_shear_and_overturning,
        drift_and_stability,
        sdof_spectral_displacement,
        # RSA
        build_asce7_spectrum,
        rsa_sdof,
        rsa_mdof,
        newmark_sdof,
        newmark_mdof,
    )

References
----------
ASCE/SEI 7-22 "Minimum Design Loads and Associated Criteria for
Buildings and Other Structures", Chapters 11–12.

Author: imranparuk
"""
from __future__ import annotations

from kerf_cad_core.seismic.elf import (
    site_coefficients,
    design_spectrum,
    approximate_period,
    seismic_response_coefficient,
    base_shear,
    vertical_distribution,
    story_shear_and_overturning,
    drift_and_stability,
    sdof_spectral_displacement,
)
from kerf_cad_core.seismic.rsa import (
    build_asce7_spectrum,
    rsa_sdof,
    rsa_mdof,
    newmark_sdof,
    newmark_mdof,
)

__all__ = [
    # ELF
    "site_coefficients",
    "design_spectrum",
    "approximate_period",
    "seismic_response_coefficient",
    "base_shear",
    "vertical_distribution",
    "story_shear_and_overturning",
    "drift_and_stability",
    "sdof_spectral_displacement",
    # RSA
    "build_asce7_spectrum",
    "rsa_sdof",
    "rsa_mdof",
    "newmark_sdof",
    "newmark_mdof",
]
