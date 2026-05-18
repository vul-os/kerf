"""sizing.py — ASHRAE velocity method for rectangular and round duct sizing.

The *velocity method* selects the smallest standard duct size whose cross-
sectional area satisfies:

    A ≥ Q / V_max

where Q is the target airflow (m³/s) and V_max is the maximum allowable
velocity (m/s).

Standard sizes follow SMACNA / ASHRAE practice:
  - Round: diameters in 25 mm increments from 100 mm to 1600 mm.
  - Rectangular: width and height rounded UP to the nearest 25 mm module,
    with aspect ratio kept ≤ 4:1 per ASHRAE recommendations.

All input/output in SI unless the _cfm/_fpm convenience wrappers are used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from kerf_hvac.duct import DuctSection, DuctShape, cfm_to_m3s, fpm_to_ms


# ---------------------------------------------------------------------------
# Standard sizes
# ---------------------------------------------------------------------------

_ROUND_SIZES_MM = list(range(100, 1650, 25))  # 100, 125, 150, ... 1625 mm


def _round_up_25(v: float) -> float:
    """Round v up to the nearest 25 mm increment."""
    return math.ceil(v / 25) * 25


# ---------------------------------------------------------------------------
# Sizing result
# ---------------------------------------------------------------------------

@dataclass
class SizingResult:
    """Result from :func:`size_duct`.

    Attributes:
        shape: Duct cross-section shape.
        width_mm: Width (rectangular / oval) or None.
        height_mm: Height (rectangular / oval) or None.
        diameter_mm: Diameter (round) or None.
        actual_velocity_m_s: Resulting mean velocity at the given airflow.
        area_m2: Cross-sectional area.
        hydraulic_diameter_m: Hydraulic diameter D_h.
        aspect_ratio: width/height for rectangular ducts; None for round.
    """

    shape: DuctShape
    width_mm: Optional[float]
    height_mm: Optional[float]
    diameter_mm: Optional[float]
    actual_velocity_m_s: float
    area_m2: float
    hydraulic_diameter_m: float
    aspect_ratio: Optional[float]

    def to_duct_section(
        self,
        length_mm: float,
        airflow_m3s: float,
        **kwargs,
    ) -> DuctSection:
        """Convenience: create a :class:`DuctSection` from this sizing result."""
        return DuctSection(
            shape=self.shape,
            length_mm=length_mm,
            airflow_m3s=airflow_m3s,
            width_mm=self.width_mm,
            height_mm=self.height_mm,
            diameter_mm=self.diameter_mm,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Core sizing function
# ---------------------------------------------------------------------------

def size_duct(
    airflow_m3s: float,
    max_velocity_m_s: float,
    shape: DuctShape = DuctShape.RECTANGULAR,
    max_aspect_ratio: float = 4.0,
    preferred_height_mm: Optional[float] = None,
) -> SizingResult:
    """Select the smallest standard duct size for the given airflow and max velocity.

    Args:
        airflow_m3s: Target airflow in m³/s.
        max_velocity_m_s: Maximum allowable duct velocity in m/s.
        shape: Desired duct cross-section shape (default: RECTANGULAR).
        max_aspect_ratio: Maximum width:height ratio for rectangular ducts
            (default 4.0, per ASHRAE).
        preferred_height_mm: For rectangular ducts, fix the height and solve
            only for width (useful when duct fits inside a ceiling plenum of
            known depth).

    Returns:
        :class:`SizingResult` describing the selected size.

    Raises:
        ValueError: If no standard size satisfies the constraints.
    """
    if airflow_m3s <= 0:
        raise ValueError("airflow_m3s must be positive")
    if max_velocity_m_s <= 0:
        raise ValueError("max_velocity_m_s must be positive")

    min_area = airflow_m3s / max_velocity_m_s

    if shape == DuctShape.ROUND:
        return _size_round(airflow_m3s, min_area)
    elif shape == DuctShape.RECTANGULAR:
        return _size_rectangular(airflow_m3s, min_area, max_aspect_ratio, preferred_height_mm)
    else:
        raise ValueError(f"size_duct: shape {shape!r} not yet supported (use ROUND or RECTANGULAR)")


def _size_round(airflow_m3s: float, min_area: float) -> SizingResult:
    """Pick smallest standard round diameter whose area ≥ min_area."""
    for d_mm in _ROUND_SIZES_MM:
        r = (d_mm / 1000) / 2
        area = math.pi * r * r
        if area >= min_area:
            velocity = airflow_m3s / area
            return SizingResult(
                shape=DuctShape.ROUND,
                width_mm=None,
                height_mm=None,
                diameter_mm=float(d_mm),
                actual_velocity_m_s=velocity,
                area_m2=area,
                hydraulic_diameter_m=d_mm / 1000,
                aspect_ratio=None,
            )
    raise ValueError(
        f"No standard round duct (up to {_ROUND_SIZES_MM[-1]} mm dia.) "
        f"is large enough for {airflow_m3s:.4f} m³/s at the given velocity."
    )


def _size_rectangular(
    airflow_m3s: float,
    min_area: float,
    max_aspect_ratio: float,
    preferred_height_mm: Optional[float],
) -> SizingResult:
    """Pick smallest rectangular duct (25 mm modular grid) satisfying constraints.

    Strategy:
    1. If preferred_height_mm is given, fix h and solve for w = ceil(A/h).
    2. Otherwise, enumerate candidate heights starting at 100 mm (25 mm steps)
       up to a height that would keep aspect ratio ≤ max_aspect_ratio, and for
       each height pick the smallest w that satisfies area and aspect ratio.
       Return the candidate with the lowest perimeter (most efficient section).
    """
    if preferred_height_mm is not None:
        h_mm = _round_up_25(preferred_height_mm)
        h = h_mm / 1000
        w = min_area / h
        w_mm = _round_up_25(w * 1000)
        w = w_mm / 1000
        area = w * h
        velocity = airflow_m3s / area
        dh = 4 * area / (2 * (w + h))
        return SizingResult(
            shape=DuctShape.RECTANGULAR,
            width_mm=w_mm,
            height_mm=h_mm,
            diameter_mm=None,
            actual_velocity_m_s=velocity,
            area_m2=area,
            hydraulic_diameter_m=dh,
            aspect_ratio=w_mm / h_mm,
        )

    # Free sizing: try all heights from 100 mm upwards, keep best perimeter
    best: Optional[SizingResult] = None
    best_perimeter = math.inf

    # Maximum reasonable height: square root of min_area (square duct) scaled by max_aspect_ratio
    max_h_mm = _round_up_25(math.sqrt(min_area * max_aspect_ratio) * 1000)
    max_h_mm = min(max_h_mm, 2000)  # cap search at 2 m

    for h_mm in range(100, int(max_h_mm) + 25, 25):
        h = h_mm / 1000
        # minimum width needed for area
        w_needed = min_area / h
        w_mm = _round_up_25(w_needed * 1000)
        w = w_mm / 1000
        aspect = w_mm / h_mm
        if aspect > max_aspect_ratio:
            continue
        area = w * h
        velocity = airflow_m3s / area
        perimeter = 2 * (w + h)
        if perimeter < best_perimeter:
            best_perimeter = perimeter
            dh = 4 * area / perimeter
            best = SizingResult(
                shape=DuctShape.RECTANGULAR,
                width_mm=float(w_mm),
                height_mm=float(h_mm),
                diameter_mm=None,
                actual_velocity_m_s=velocity,
                area_m2=area,
                hydraulic_diameter_m=dh,
                aspect_ratio=aspect,
            )

    if best is None:
        raise ValueError(
            f"No rectangular duct satisfies {airflow_m3s:.4f} m³/s with "
            f"aspect ratio ≤ {max_aspect_ratio}."
        )
    return best


# ---------------------------------------------------------------------------
# Convenience wrappers (imperial inputs)
# ---------------------------------------------------------------------------

def size_duct_cfm_fpm(
    airflow_cfm: float,
    max_velocity_fpm: float,
    shape: DuctShape = DuctShape.RECTANGULAR,
    max_aspect_ratio: float = 4.0,
    preferred_height_mm: Optional[float] = None,
) -> SizingResult:
    """Convenience wrapper accepting airflow in CFM and velocity in FPM."""
    return size_duct(
        airflow_m3s=cfm_to_m3s(airflow_cfm),
        max_velocity_m_s=fpm_to_ms(max_velocity_fpm),
        shape=shape,
        max_aspect_ratio=max_aspect_ratio,
        preferred_height_mm=preferred_height_mm,
    )
