"""
kerf_composites.failure_depth — Extended failure criteria with mode detection.

Implements:
  - Tsai-Wu quadratic failure index with margin of safety
  - Tsai-Hill failure criterion
  - Max-stress / max-strain independent component checks
  - Hashin (1980) fiber/matrix failure mode discrimination

All criteria operate on ply-level principal-axis stresses (σ₁, σ₂, τ₁₂) in MPa
and return a FailureResult carrying the failure index, margin of safety, and
failure mode identifier.

References
----------
Tsai, S. W. & Wu, E. M. (1971). A general theory of strength for anisotropic
    materials. J. Composite Materials, 5, 58–80.
Hashin, Z. (1980). Failure criteria for unidirectional fiber composites.
    J. Applied Mechanics, 47, 329–334.
Hill, R. (1950). The Mathematical Theory of Plasticity. Oxford.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kerf_composites.layup import PlyMaterial


# ---------------------------------------------------------------------------
# Failure mode enum
# ---------------------------------------------------------------------------

class FailureMode(Enum):
    """Failure mode classification."""
    NONE = "none"
    FIBER_TENSION = "fiber_tension"
    FIBER_COMPRESSION = "fiber_compression"
    MATRIX_TENSION = "matrix_tension"
    MATRIX_COMPRESSION = "matrix_compression"
    SHEAR = "shear"
    COMBINED = "combined"


# ---------------------------------------------------------------------------
# Failure result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FailureResult:
    """
    Result from a single failure criterion evaluation.

    Attributes
    ----------
    failure_index : float
        Dimensionless failure index (FI).  FI ≥ 1 → failure predicted.
    margin_of_safety : float
        MS = 1/FI − 1.  MS ≥ 0 → safe; MS < 0 → failed.
        Infinite when FI ≤ 0 (compressive–compressive biaxial, etc.).
    failed : bool
        True when failure_index ≥ 1.
    mode : FailureMode
        Failure mode identified by the criterion.
    criterion : str
        Human-readable name of the criterion used.
    """
    failure_index: float
    margin_of_safety: float
    failed: bool
    mode: FailureMode
    criterion: str


def _result(fi: float, criterion: str, mode: FailureMode) -> FailureResult:
    if fi <= 0.0:
        ms = float("inf")
    else:
        ms = 1.0 / fi - 1.0
    return FailureResult(
        failure_index=fi,
        margin_of_safety=ms,
        failed=(fi >= 1.0),
        mode=mode,
        criterion=criterion,
    )


# ---------------------------------------------------------------------------
# Tsai-Wu failure index (Tsai & Wu, 1971)
# ---------------------------------------------------------------------------

def tsai_wu(
    sigma1: float,
    sigma2: float,
    tau12: float,
    material: "PlyMaterial",
    F12_star: float = -0.5,
) -> FailureResult:
    """
    Tsai-Wu quadratic failure criterion.

    FI = F₁σ₁ + F₂σ₂ + F₁₁σ₁² + F₂₂σ₂² + F₆₆τ₁₂² + 2F₁₂σ₁σ₂

    where
      F₁  = 1/Xt − 1/Xc
      F₂  = 1/Yt − 1/Yc
      F₁₁ = 1/(Xt·Xc)
      F₂₂ = 1/(Yt·Yc)
      F₆₆ = 1/S₁₂²
      F₁₂ = F12_star · √(F₁₁·F₂₂)   (interaction; default −0.5 per Tsai-Wu)

    Parameters
    ----------
    sigma1, sigma2 : float
        Principal-axis in-plane stresses [MPa].  + = tension.
    tau12 : float
        In-plane shear stress [MPa].
    material : PlyMaterial
        Ply material with strength allowables [MPa].
    F12_star : float
        Normalised interaction coefficient (default −0.5, conservative).

    Returns
    -------
    FailureResult
    """
    m = material
    s1, s2, t12 = sigma1, sigma2, tau12

    F1 = 1.0 / m.Xt - 1.0 / m.Xc
    F2 = 1.0 / m.Yt - 1.0 / m.Yc
    F11 = 1.0 / (m.Xt * m.Xc)
    F22 = 1.0 / (m.Yt * m.Yc)
    F66 = 1.0 / (m.S12 ** 2)
    F12 = F12_star * math.sqrt(F11 * F22)

    fi = (
        F1 * s1
        + F2 * s2
        + F11 * s1 ** 2
        + F22 * s2 ** 2
        + F66 * t12 ** 2
        + 2.0 * F12 * s1 * s2
    )
    return _result(fi, "Tsai-Wu", FailureMode.COMBINED)


# ---------------------------------------------------------------------------
# Tsai-Hill failure index (Hill, 1950; Tsai, 1968)
# ---------------------------------------------------------------------------

def tsai_hill(
    sigma1: float,
    sigma2: float,
    tau12: float,
    material: "PlyMaterial",
) -> FailureResult:
    """
    Tsai-Hill failure criterion.

    FI = (σ₁/X)² − (σ₁σ₂/X²) + (σ₂/Y)² + (τ₁₂/S₁₂)²

    where X = Xt if σ₁ ≥ 0 else Xc, Y = Yt if σ₂ ≥ 0 else Yc.

    Special case: for uniaxial σ₁-only (σ₂ = τ₁₂ = 0) this reduces to the
    von Mises uniaxial form FI = (σ₁/X)², so failure occurs at σ₁ = X.

    Parameters
    ----------
    sigma1, sigma2 : float
        Principal-axis in-plane stresses [MPa].
    tau12 : float
        In-plane shear stress [MPa].
    material : PlyMaterial

    Returns
    -------
    FailureResult
    """
    m = material
    s1, s2, t12 = sigma1, sigma2, tau12

    X = m.Xt if s1 >= 0.0 else m.Xc
    Y = m.Yt if s2 >= 0.0 else m.Yc

    fi = (
        (s1 / X) ** 2
        - (s1 * s2 / X ** 2)
        + (s2 / Y) ** 2
        + (t12 / m.S12) ** 2
    )
    return _result(fi, "Tsai-Hill", FailureMode.COMBINED)


# ---------------------------------------------------------------------------
# Max-stress criterion
# ---------------------------------------------------------------------------

@dataclass
class MaxStressResult:
    """
    Result from the max-stress criterion.

    Each component is checked independently against its allowable.
    Failure occurs when any component ratio ≥ 1.
    """
    fi_sigma1: float    # |σ₁| / X (Xt or Xc depending on sign)
    fi_sigma2: float    # |σ₂| / Y
    fi_tau12: float     # |τ₁₂| / S₁₂
    failure_index: float  # max of the three
    margin_of_safety: float
    failed: bool
    mode: FailureMode
    criterion: str = "Max-stress"


def max_stress(
    sigma1: float,
    sigma2: float,
    tau12: float,
    material: "PlyMaterial",
) -> MaxStressResult:
    """
    Maximum stress failure criterion — each component independently.

    FI_i = |σᵢ| / allowable_i

    The overall failure index is max(FI_1, FI_2, FI_6) and the controlling
    mode is reported.

    Parameters
    ----------
    sigma1, sigma2 : float  [MPa]
    tau12 : float           [MPa]
    material : PlyMaterial

    Returns
    -------
    MaxStressResult
    """
    m = material
    X = m.Xt if sigma1 >= 0.0 else m.Xc
    Y = m.Yt if sigma2 >= 0.0 else m.Yc

    fi1 = abs(sigma1) / X
    fi2 = abs(sigma2) / Y
    fi6 = abs(tau12) / m.S12

    fi = max(fi1, fi2, fi6)
    ms = (1.0 / fi - 1.0) if fi > 0.0 else float("inf")

    # Determine dominant mode
    if fi == fi1:
        mode = FailureMode.FIBER_TENSION if sigma1 >= 0.0 else FailureMode.FIBER_COMPRESSION
    elif fi == fi2:
        mode = FailureMode.MATRIX_TENSION if sigma2 >= 0.0 else FailureMode.MATRIX_COMPRESSION
    else:
        mode = FailureMode.SHEAR

    return MaxStressResult(
        fi_sigma1=fi1,
        fi_sigma2=fi2,
        fi_tau12=fi6,
        failure_index=fi,
        margin_of_safety=ms,
        failed=(fi >= 1.0),
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Max-strain criterion
# ---------------------------------------------------------------------------

@dataclass
class MaxStrainResult:
    """Result from the max-strain criterion."""
    fi_eps1: float
    fi_eps2: float
    fi_gamma12: float
    failure_index: float
    margin_of_safety: float
    failed: bool
    mode: FailureMode
    criterion: str = "Max-strain"


def max_strain(
    sigma1: float,
    sigma2: float,
    tau12: float,
    material: "PlyMaterial",
    eps1t_allow: float | None = None,
    eps1c_allow: float | None = None,
    eps2t_allow: float | None = None,
    eps2c_allow: float | None = None,
    gamma12_allow: float | None = None,
) -> MaxStrainResult:
    """
    Maximum strain failure criterion.

    Strains are computed from stresses using the ply compliance.  Allowable
    strains default to strength / modulus (linear–elastic approximation) if
    not provided.

    Parameters
    ----------
    sigma1, sigma2 : float  [MPa]
    tau12 : float           [MPa]
    material : PlyMaterial
    eps1t_allow, eps1c_allow : float, optional
        Tensile / compressive ultimate fibre-direction strains (dimensionless).
        Default: Xt / E1 / 1000, Xc / E1 / 1000  (moduli in GPa → /1000 → MPa).
    eps2t_allow, eps2c_allow : float, optional
        Ultimate transverse strains.  Default: Yt / E2 / 1000, Yc / E2 / 1000.
    gamma12_allow : float, optional
        Ultimate shear strain.  Default: S12 / G12 / 1000.

    Returns
    -------
    MaxStrainResult
    """
    m = material
    # GPa to MPa: E1_mpa = E1 * 1000
    E1_mpa = m.E1 * 1e3
    E2_mpa = m.E2 * 1e3
    G12_mpa = m.G12 * 1e3
    nu12 = m.nu12
    nu21 = m.nu21

    # Strain from CLT compliance (in-plane, uncoupled for UD ply in principal axes)
    eps1 = sigma1 / E1_mpa - nu21 * sigma2 / E2_mpa
    eps2 = sigma2 / E2_mpa - nu12 * sigma1 / E1_mpa
    gamma12 = tau12 / G12_mpa

    # Allowables
    a1t = eps1t_allow if eps1t_allow is not None else m.Xt / E1_mpa
    a1c = eps1c_allow if eps1c_allow is not None else m.Xc / E1_mpa
    a2t = eps2t_allow if eps2t_allow is not None else m.Yt / E2_mpa
    a2c = eps2c_allow if eps2c_allow is not None else m.Yc / E2_mpa
    a6  = gamma12_allow if gamma12_allow is not None else m.S12 / G12_mpa

    al1 = a1t if eps1 >= 0.0 else a1c
    al2 = a2t if eps2 >= 0.0 else a2c

    fi1 = abs(eps1) / al1 if al1 > 0.0 else float("inf")
    fi2 = abs(eps2) / al2 if al2 > 0.0 else float("inf")
    fi6 = abs(gamma12) / a6 if a6 > 0.0 else float("inf")

    fi = max(fi1, fi2, fi6)
    ms = (1.0 / fi - 1.0) if fi > 0.0 else float("inf")

    if fi == fi1:
        mode = FailureMode.FIBER_TENSION if eps1 >= 0.0 else FailureMode.FIBER_COMPRESSION
    elif fi == fi2:
        mode = FailureMode.MATRIX_TENSION if eps2 >= 0.0 else FailureMode.MATRIX_COMPRESSION
    else:
        mode = FailureMode.SHEAR

    return MaxStrainResult(
        fi_eps1=fi1,
        fi_eps2=fi2,
        fi_gamma12=fi6,
        failure_index=fi,
        margin_of_safety=ms,
        failed=(fi >= 1.0),
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Hashin (1980) failure criteria
# ---------------------------------------------------------------------------

@dataclass
class HashinResult:
    """
    Result from Hashin (1980) mode-discriminating failure criteria.

    Four sub-criteria are evaluated; the critical (largest) FI is reported.

    Attributes
    ----------
    fi_fiber_tension : float
        Fiber-tension failure index (σ₁ > 0).
    fi_fiber_compression : float
        Fiber-compression failure index (σ₁ < 0).
    fi_matrix_tension : float
        Matrix-tension failure index (σ₂ > 0).
    fi_matrix_compression : float
        Matrix-compression failure index (σ₂ < 0).
    failure_index : float
        max of the four sub-criteria.
    margin_of_safety : float
    failed : bool
    mode : FailureMode
        The controlling failure mode.
    criterion : str
    """
    fi_fiber_tension: float
    fi_fiber_compression: float
    fi_matrix_tension: float
    fi_matrix_compression: float
    failure_index: float
    margin_of_safety: float
    failed: bool
    mode: FailureMode
    criterion: str = "Hashin"


def hashin(
    sigma1: float,
    sigma2: float,
    tau12: float,
    material: "PlyMaterial",
    alpha: float = 1.0,
) -> HashinResult:
    """
    Hashin (1980) mode-discriminating failure criteria.

    Fiber tension  (σ₁ ≥ 0):
        FI_ft = (σ₁/Xt)² + α·(τ₁₂/S₁₂)²

    Fiber compression  (σ₁ < 0):
        FI_fc = (σ₁/Xc)²

    Matrix tension  (σ₂ ≥ 0):
        FI_mt = (σ₂/Yt)² + (τ₁₂/S₁₂)²

    Matrix compression  (σ₂ < 0):
        FI_mc = (σ₂/(2·S₁₂))² + [(Yc/(2·S₁₂))² − 1]·(σ₂/Yc) + (τ₁₂/S₁₂)²

    Parameters
    ----------
    sigma1, sigma2 : float  [MPa]
    tau12 : float           [MPa]
    material : PlyMaterial
    alpha : float
        Fiber-tension shear contribution factor (0 or 1).  Default 1
        (include shear in fiber tension, per Hashin 1980 3D form).

    Returns
    -------
    HashinResult
    """
    m = material
    s1, s2, t12 = sigma1, sigma2, tau12

    # Fiber tension
    fi_ft = (s1 / m.Xt) ** 2 + alpha * (t12 / m.S12) ** 2 if s1 >= 0.0 else 0.0

    # Fiber compression
    fi_fc = (s1 / m.Xc) ** 2 if s1 < 0.0 else 0.0

    # Matrix tension
    fi_mt = (s2 / m.Yt) ** 2 + (t12 / m.S12) ** 2 if s2 >= 0.0 else 0.0

    # Matrix compression
    if s2 < 0.0:
        term1 = (s2 / (2.0 * m.S12)) ** 2
        term2 = ((m.Yc / (2.0 * m.S12)) ** 2 - 1.0) * (s2 / m.Yc)
        term3 = (t12 / m.S12) ** 2
        fi_mc = term1 + term2 + term3
    else:
        fi_mc = 0.0

    # Overall
    fi = max(fi_ft, fi_fc, fi_mt, fi_mc)
    ms = (1.0 / fi - 1.0) if fi > 0.0 else float("inf")

    # Controlling mode
    fi_map = {
        fi_ft: FailureMode.FIBER_TENSION,
        fi_fc: FailureMode.FIBER_COMPRESSION,
        fi_mt: FailureMode.MATRIX_TENSION,
        fi_mc: FailureMode.MATRIX_COMPRESSION,
    }
    # Resolve ties in a deterministic priority order
    for fi_val, mode_val in [
        (fi_ft, FailureMode.FIBER_TENSION),
        (fi_fc, FailureMode.FIBER_COMPRESSION),
        (fi_mt, FailureMode.MATRIX_TENSION),
        (fi_mc, FailureMode.MATRIX_COMPRESSION),
    ]:
        if fi_val == fi:
            mode = mode_val
            break
    else:
        mode = FailureMode.COMBINED

    return HashinResult(
        fi_fiber_tension=fi_ft,
        fi_fiber_compression=fi_fc,
        fi_matrix_tension=fi_mt,
        fi_matrix_compression=fi_mc,
        failure_index=fi,
        margin_of_safety=ms,
        failed=(fi >= 1.0),
        mode=mode,
    )
