"""
Rebar detailing per ACI 318-19.

Covers:
- Bar mark lookup (bar number → diameter, area, weight)
- Development length  §25.5.2
- Lap-splice length   §25.5.5 (Class A and Class B)
- Hook development    §25.4.3 (standard 90° and 180° hooks)

All units are US customary: inches, psi, lb/ft.

References
----------
ACI 318-19 §25.4, §25.5
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Bar mark table
# ---------------------------------------------------------------------------

# Bar mark → (nominal diameter in, nominal area in², weight lb/ft)
_BAR_TABLE: dict[int, tuple[float, float, float]] = {
    3:  (0.375,  0.11,  0.376),
    4:  (0.500,  0.20,  0.668),
    5:  (0.625,  0.31,  1.043),
    6:  (0.750,  0.44,  1.502),
    7:  (0.875,  0.60,  2.044),
    8:  (1.000,  0.79,  2.670),
    9:  (1.128,  1.00,  3.400),
    10: (1.270,  1.27,  4.303),
    11: (1.410,  1.56,  5.313),
    14: (1.693,  2.25,  7.650),
    18: (2.257,  4.00, 13.600),
}


@dataclass
class BarInfo:
    bar_mark: int
    diameter: float    # in
    area: float        # in²
    weight: float      # lb/ft


def bar_info(bar_mark: int) -> BarInfo:
    """
    Return nominal properties for a US rebar mark.

    Parameters
    ----------
    bar_mark : int
        Standard bar designation number (3–18).

    Raises
    ------
    ValueError
        If bar_mark is not in the standard table.
    """
    if bar_mark not in _BAR_TABLE:
        raise ValueError(
            f"Bar #{bar_mark} not recognised. Valid marks: {sorted(_BAR_TABLE)}"
        )
    db, ab, wt = _BAR_TABLE[bar_mark]
    return BarInfo(bar_mark=bar_mark, diameter=db, area=ab, weight=wt)


# ---------------------------------------------------------------------------
# Development length  ACI 318-19 §25.5.2
# ---------------------------------------------------------------------------

def development_length(
    bar_mark: int,
    *,
    fc: float = 4_000.0,
    fy: float = 60_000.0,
    psi_t: float = 1.0,
    psi_e: float = 1.0,
    lambda_factor: float = 1.0,
    cb_Ktr_db: float = 2.5,
) -> float:
    """
    Tension development length l_d (inches) per ACI 318-19 §25.5.2.1.

    Parameters
    ----------
    bar_mark : int
        Bar designation number.
    fc : float
        Concrete f'c (psi). Default 4 000 psi.
    fy : float
        Steel yield strength (psi). Default 60 000 psi.
    psi_t : float
        Casting-position factor (1.3 for top bars, 1.0 otherwise).
    psi_e : float
        Epoxy-coating factor (1.5, 1.2, or 1.0).
    lambda_factor : float
        Lightweight concrete factor (0.75 lightweight, 1.0 normal-weight).
    cb_Ktr_db : float
        Confinement factor (c_b + K_tr)/d_b, capped at 2.5 per §25.5.2.1.

    Returns
    -------
    float
        l_d in inches (minimum 12 in).
    """
    info = bar_info(bar_mark)
    db = info.diameter

    # Size factor psi_s (§25.5.2.1 Table 25.5.2.1)
    psi_s = 0.8 if bar_mark <= 6 else 1.0

    # Cap confinement factor per code
    ratio = min(cb_Ktr_db, 2.5)

    # ACI 318-19 Table 25.5.2.1 — detailed formula
    #   l_d = (3/40) * (fy / (lambda * sqrt(f'c))) * (psi_t * psi_e * psi_s / ((cb+Ktr)/db)) * db
    ld = (3.0 / 40.0) * (fy / (lambda_factor * math.sqrt(fc))) * (
        psi_t * psi_e * psi_s / ratio
    ) * db

    # Minimum l_d = 12 in per §25.5.2.1(c)
    return max(ld, 12.0)


# ---------------------------------------------------------------------------
# Lap-splice length  ACI 318-19 §25.5.5
# ---------------------------------------------------------------------------

def lap_splice_length(
    bar_mark: int,
    splice_class: str = "B",
    *,
    fc: float = 4_000.0,
    fy: float = 60_000.0,
    psi_t: float = 1.0,
    psi_e: float = 1.0,
    lambda_factor: float = 1.0,
    cb_Ktr_db: float = 2.5,
) -> float:
    """
    Tension lap-splice length l_st (inches) per ACI 318-19 §25.5.5.

    Parameters
    ----------
    bar_mark : int
        Bar designation number.
    splice_class : {'A', 'B'}
        Class A: 1.0 × l_d (≥ 50% of bars spliced, adequate spacing).
        Class B: 1.3 × l_d (default; when more than 50% spliced or spacing < 2×bar).
    fc, fy, psi_t, psi_e, lambda_factor, cb_Ktr_db :
        Same as :func:`development_length`.

    Returns
    -------
    float
        Lap-splice length in inches.

    Raises
    ------
    ValueError
        If splice_class is not 'A' or 'B'.
    """
    splice_class = splice_class.upper()
    if splice_class not in ("A", "B"):
        raise ValueError("splice_class must be 'A' or 'B'")

    ld = development_length(
        bar_mark,
        fc=fc,
        fy=fy,
        psi_t=psi_t,
        psi_e=psi_e,
        lambda_factor=lambda_factor,
        cb_Ktr_db=cb_Ktr_db,
    )

    factor = 1.0 if splice_class == "A" else 1.3
    return factor * ld


# ---------------------------------------------------------------------------
# Standard hook development  ACI 318-19 §25.4.3
# ---------------------------------------------------------------------------

def hook_development_length(
    bar_mark: int,
    *,
    fc: float = 4_000.0,
    fy: float = 60_000.0,
    psi_e: float = 1.0,
    psi_r: float = 1.0,
    psi_o: float = 1.0,
    psi_c: float = 1.0,
    lambda_factor: float = 1.0,
) -> float:
    """
    Development length of a standard hook l_dh (inches) per ACI 318-19 §25.4.3.1.

    l_dh = (fy * psi_e * psi_r * psi_o * psi_c) / (55 * lambda * sqrt(f'c)) * db

    Parameters
    ----------
    bar_mark : int
        Bar designation.
    fc : float
        Concrete f'c (psi).
    fy : float
        Steel yield (psi).
    psi_e : float  Epoxy-coating factor.
    psi_r : float  Confinement factor (1.0 or 0.8).
    psi_o : float  Location factor (1.0 or 1.25 for side-cover < 6 in).
    psi_c : float  Cover factor.
    lambda_factor : float  Lightweight factor.

    Returns
    -------
    float
        l_dh in inches (minimum 8*db or 6 in).
    """
    info = bar_info(bar_mark)
    db = info.diameter

    ldh = (fy * psi_e * psi_r * psi_o * psi_c) / (
        55.0 * lambda_factor * math.sqrt(fc)
    ) * db

    return max(ldh, 8.0 * db, 6.0)
