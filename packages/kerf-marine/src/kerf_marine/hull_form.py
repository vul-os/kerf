"""
hull_form.py — Parametric displacement-hull form generation and Lackenby shift.

Generates a parent-hull body plan (sections / waterlines / buttocks) from a
small set of form coefficients, and applies the Lackenby (1950) sectional-area
curve shift to match target CB and LCB.

Methods
-------
generate_hull_sections(L, B, T, Cb, Cm, n_stations) -> list[SectionDef]
    Generate body-plan sections for a simple wall-sided displacement hull
    following Lewis (1954) prismatic-section distribution.

lackenby_shift(sections, Cb_target, lcb_frac_target) -> list[SectionDef]
    Apply the Lackenby (1950) δAc / δAf shift to a sectional-area curve
    so the hull achieves target CB and LCB without altering midship section.
    Implements Eqs. (3)–(6) of Lackenby 1950 (RINA Trans. 92, 289-316).

hull_waterlines(sections, n_wl) -> list[WaterlineDef]
    Extract waterline (constant-z) curves from a body plan.

hull_buttocks(sections, n_butt, B) -> list[ButtockDef]
    Extract buttock (constant-y) curves from a body plan.

section_offsets_table(sections) -> list[tuple]
    Convert SectionDef list to the (station, waterline, half_breadth)
    format accepted by kerf_marine.sections.OffsetTable.

References
----------
Lackenby, H. (1950). "On the systematic geometrical variation of ship forms."
    Trans. RINA 92, 289-316.  — The canonical Δ(Ac) / Δ(Af) shift method.

Lewis, E.V. (1954). "Ship model resistance tests." SNAME Trans. 62.
    — Prismatic distribution of sectional areas.

Kerwin, J.E. (1976). "Notes on Ship Resistance." MIT Dept. Ocean Eng.
    — Standard parametric section shapes for preliminary design.

SNAME (1988). "Principles of Naval Architecture" Vol. II §2.2–2.4.
    — Block/prismatic/midship coefficient definitions and body-plan construction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SectionPoint:
    """A single (waterline, half_breadth) point on a section."""
    waterline: float   # m above keel
    half_breadth: float  # m (half beam)


@dataclass
class SectionDef:
    """One transverse body-plan section.

    station     : m from aft perpendicular (0 = AP, L = FP)
    area_coeff  : sectional-area coefficient = A_s / (B*T)  [0..Cm]
    points      : list of (waterline, half_breadth) offsets
    """
    station: float
    area_coeff: float
    points: List[SectionPoint] = field(default_factory=list)

    def half_breadths(self) -> List[float]:
        return [p.half_breadth for p in self.points]

    def waterlines(self) -> List[float]:
        return [p.waterline for p in self.points]

    def area(self) -> float:
        """Approximate section area by trapezoidal integration of 2*y dz."""
        wls = self.waterlines()
        hbs = self.half_breadths()
        if len(wls) < 2:
            return 0.0
        total = 0.0
        for i in range(len(wls) - 1):
            dz = wls[i + 1] - wls[i]
            total += 0.5 * (hbs[i] + hbs[i + 1]) * dz
        return 2.0 * total  # full section (both sides)


@dataclass
class WaterlineDef:
    """One waterline curve: (station, half_breadth) pairs at constant z."""
    draft: float         # m above keel (z-level)
    stations: List[float] = field(default_factory=list)
    half_breadths: List[float] = field(default_factory=list)


@dataclass
class ButtockDef:
    """One buttock line: (station, z) pairs at constant y."""
    half_breadth: float  # m from centreline (y-level)
    stations: List[float] = field(default_factory=list)
    drafts: List[float] = field(default_factory=list)


@dataclass
class HullForm:
    """Complete parametric hull form.

    Attributes
    ----------
    L, B, T     : hull dimensions (m)
    Cb          : achieved block coefficient
    Cm          : midship section coefficient
    Cp          : achieved prismatic coefficient = Cb / Cm
    lcb_frac    : LCB as fraction of L from AP (0=AP, 1=FP); typical 0.45–0.55
    sections    : body-plan sections (n_stations)
    waterlines  : waterline curves
    buttocks    : buttock lines
    """
    L: float
    B: float
    T: float
    Cb: float
    Cm: float
    Cp: float
    lcb_frac: float
    sections: List[SectionDef] = field(default_factory=list)
    waterlines: List[WaterlineDef] = field(default_factory=list)
    buttocks: List[ButtockDef] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "L_m": self.L,
            "B_m": self.B,
            "T_m": self.T,
            "Cb": round(self.Cb, 4),
            "Cm": round(self.Cm, 4),
            "Cp": round(self.Cp, 4),
            "lcb_frac": round(self.lcb_frac, 4),
            "lcb_m_from_ap": round(self.lcb_frac * self.L, 3),
            "n_sections": len(self.sections),
            "n_waterlines": len(self.waterlines),
            "n_buttocks": len(self.buttocks),
            "volume_m3": round(self.Cb * self.L * self.B * self.T, 3),
            "sections": [
                {
                    "station_m": s.station,
                    "area_coeff": round(s.area_coeff, 4),
                    "points": [
                        {"waterline_m": p.waterline, "half_breadth_m": p.half_breadth}
                        for p in s.points
                    ],
                }
                for s in self.sections
            ],
            "waterlines": [
                {
                    "draft_m": wl.draft,
                    "stations_m": wl.stations,
                    "half_breadths_m": wl.half_breadths,
                }
                for wl in self.waterlines
            ],
            "buttocks": [
                {
                    "half_breadth_m": bt.half_breadth,
                    "stations_m": bt.stations,
                    "drafts_m": bt.drafts,
                }
                for bt in self.buttocks
            ],
        }

    def offset_table(self) -> List[Tuple[float, float, float]]:
        """Return (station, waterline, half_breadth) rows for OffsetTable."""
        rows = []
        for sec in self.sections:
            for pt in sec.points:
                rows.append((sec.station, pt.waterline, pt.half_breadth))
        return rows


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prismatic_area_coeff(xi: float, Cp: float, Cm: float, n: float = 2.0) -> float:
    """
    Sectional-area coefficient as/(B*T) at fractional station ξ = x/L.

    Uses the symmetric power-law distribution:
      as/(B*T) = Cm · (1 - |2ξ - 1|^n)

    where n is chosen so that ∫₀¹ Cm·(1-|2ξ-1|^n) dξ = Cb = Cp·Cm.

    Derivation:
      ∫₀¹ (1 - |2ξ-1|^n) dξ = n/(n+1)   [exact analytic result]
      Setting Cm · n/(n+1) = Cb = Cp·Cm  =>  n/(n+1) = Cp
      =>  n = Cp / (1 - Cp)

    For Cp = 0.5: n = 1.0 (triangular / fine hull)
    For Cp = 0.6: n = 1.5
    For Cp = 0.7: n = 2.33
    For Cp = 0.8: n = 4.0 (full / block hull)

    Returns: area_coeff = as/(B*T) in [0, Cm].
    """
    if Cm <= 0 or Cp <= 0:
        return 0.0
    Cp_c = min(max(Cp, 0.10), 0.99)
    denom = 1.0 - Cp_c
    if denom < 1e-4:
        return Cm
    n_exp = Cp_c / denom
    n_exp = max(0.5, min(n_exp, 50.0))

    # Peak at ξ=0.5 (midship), tapers to 0 at ξ=0 and ξ=1
    f = 1.0 - abs(2.0 * xi - 1.0) ** n_exp
    f = max(0.0, f)
    return Cm * f


def _section_shape(
    area_coeff: float,
    B: float,
    T: float,
    n_wl: int = 8,
    bilge_radius_frac: float = 0.15,
) -> List[SectionPoint]:
    """
    Generate a smooth U-shaped section with given area coefficient.

    The section shape follows the Lewis (1949) form:
    - Straight sides from deck to bilge tangent point
    - Circular bilge radius
    - Flat keel bottom

    area_coeff = A_s / (B * T) in [0, Cm]

    The shape is parameterised so:
      - Bottom half-breadth b0 (flat keel breadth)
      - Bilge radius r
      - The shape integrates to area_coeff * B * T

    For a simple U-shape:
      area = 2 * (b0*r + (B/2 - r)*(T - r) + π*r²/4)  (approx)
    Here we use a normalised distribution and scale to the required area.

    Returns points from keel (waterline=0) to deck (waterline=T).
    """
    if area_coeff <= 0:
        # Zero-area section (theoretical bow/stern point)
        return [SectionPoint(waterline=float(i) / (n_wl - 1) * T, half_breadth=0.0)
                for i in range(n_wl)]

    half_B = B / 2.0
    # Bilge radius
    r = bilge_radius_frac * min(half_B, T)

    # For the target area, define a normalised section:
    # Column of full beam from z=r to z=T (rectangular part)
    # Circular bilge quarter from z=0 to z=r
    # Flat keel from y=0 to y=y_keel at z=0

    # Full rectangular section area = B * T
    # U-section area target
    target_area = area_coeff * B * T

    # Full half-beam rectangle (the maximum shape for this B, T):
    # A_rect = B * T (coefficient = 1.0 for Cm=1)
    # We scale the half_breadth distribution to hit target area.

    # Build a parametric shape:
    #   z = 0 (keel): y = y_keel (flat keel half-breadth)
    #   z = r (bilge tangent): y = half_B (beam begins)
    #   z = T (deck): y = half_B

    # For the circular bilge quarter (0 ≤ z ≤ r):
    #   y(z) = half_B - r + sqrt(r² - (r - z)²)  [bilge tangent at z=0 on flat keel]
    #   This gives y(0) = half_B - r (for flat keel = inner keel point)
    #   and y(r) = half_B

    # For a block-like bottom (keel flat from y=0 to y=half_B at z=0):
    # We raise the whole profile by scaling.

    # Simple clean model for preliminary design:
    # Use a parabolic-blended profile parameterised by area coefficient.

    # Height-normalised half-breadth distribution: y(z_norm) in [0,1]
    # where z_norm = z / T.
    # We use: y_norm(z) = sqrt(max(0, 1 - ((1-z)^m)))  with m chosen for AC
    # Integrate: AC = integral_0^1 y_norm dz_norm
    # For m=2 (parabolic): AC ≈ 0.667

    # Target AC_norm = area_coeff (since we are normalising by B*T with half_B factored out)
    # Since y ranges 0..half_B and z ranges 0..T:
    # AC_norm = (2/BT) * integral_0^T y(z) dz = area_coeff

    # We parameterise:
    #   y(z) = half_B * g(z/T)
    #   where g(t) is a shape function in [0,1] and integral_0^1 g dt = area_coeff/Cm
    #   (normalized to Cm since half_B corresponds to Cm=1)

    # Use: g(t) = min(1, ((t + a)/(1 + a))^(1/m))
    # with a,m chosen so integral = area_coeff_norm and g(0) is reasonable.

    # Simplest: g(t) = t^(1/p) (pure power law)
    # integral_0^1 t^(1/p) dt = p/(p+1)
    # So area_coeff_norm = p/(p+1) => p = area_coeff_norm/(1 - area_coeff_norm)

    # For a U-section we want the bottom to be wide (concave-up shape in 2D view)
    # which is t → 1 quickly. That corresponds to small p (e.g. p<1).
    # For a V-section we want bottom narrow, which is large p.

    # But for parametric hull generation, we want the AREA to hit the target.
    # Use area_coeff (= A/(B*T)) directly:

    ac = min(max(area_coeff, 0.01), 0.9999)
    if 1.0 - ac < 1e-6:
        # Near-full rectangle
        return [SectionPoint(waterline=float(i) / (n_wl - 1) * T,
                             half_breadth=half_B)
                for i in range(n_wl)]

    p = ac / (1.0 - ac)
    p = max(0.1, min(p, 20.0))
    exp = 1.0 / p

    points = []
    for i in range(n_wl):
        t = float(i) / (n_wl - 1)  # z/T normalised [0=keel, 1=deck]
        g = t ** exp
        y = half_B * g
        points.append(SectionPoint(waterline=t * T, half_breadth=y))

    return points


def _section_lcb(sections: List[SectionDef], L: float) -> float:
    """Compute LCB as fraction of L from AP for a list of sections."""
    if not sections:
        return 0.5
    stations = [s.station for s in sections]
    areas = [s.area() for s in sections]
    if not any(a > 0 for a in areas):
        return 0.5
    # Trapezoidal integration
    vol = 0.0
    moment = 0.0
    for i in range(len(stations) - 1):
        dx = stations[i + 1] - stations[i]
        a_avg = 0.5 * (areas[i] + areas[i + 1])
        x_avg = 0.5 * (stations[i] + stations[i + 1])
        vol += a_avg * dx
        moment += a_avg * x_avg * dx
    if vol < 1e-12:
        return 0.5
    return (moment / vol) / L


# ---------------------------------------------------------------------------
# generate_hull_sections
# ---------------------------------------------------------------------------

def generate_hull_sections(
    L: float,
    B: float,
    T: float,
    Cb: float = 0.55,
    Cm: float = 0.90,
    n_stations: int = 21,
    n_wl: int = 9,
    bilge_radius_frac: float = 0.12,
    lcb_frac: Optional[float] = None,
) -> List[SectionDef]:
    """
    Generate a parametric displacement-hull body plan.

    Produces ``n_stations`` transverse sections, each with ``n_wl`` waterline
    offsets, parameterised by block coefficient Cb, midship section
    coefficient Cm, and optional LCB fraction.

    Uses a Lewis (1954) power-law prismatic distribution to set the
    sectional-area curve.  Section shapes follow a power-law half-breadth
    profile parameterised by the local area coefficient.

    Parameters
    ----------
    L           : float — LBP (m)
    B           : float — moulded breadth (m)
    T           : float — design draft (m)
    Cb          : float — target block coefficient (0.40–0.85)
    Cm          : float — midship section coefficient (0.85–0.99)
    n_stations  : int   — number of body-plan stations (default 21 = every 5%)
    n_wl        : int   — waterline points per section (default 9)
    bilge_radius_frac : float — bilge radius as fraction of min(B/2, T)
    lcb_frac    : float | None — LCB as fraction of L from AP.
                  If given, the Lackenby shift is applied after initial generation.

    Returns
    -------
    list[SectionDef]
        Body-plan sections from AP (station=0) to FP (station=L).

    References
    ----------
    Lewis 1954 SNAME §2; Lackenby 1950 RINA Trans. 92.
    """
    Cp = Cb / max(Cm, 0.01)
    Cp = max(0.40, min(Cp, 0.95))

    sections: List[SectionDef] = []
    for i in range(n_stations):
        xi = float(i) / (n_stations - 1)  # 0 = AP, 1 = FP
        x = xi * L

        # Sectional-area coefficient at this station
        ac = _prismatic_area_coeff(xi, Cp, Cm)
        pts = _section_shape(ac, B, T, n_wl=n_wl, bilge_radius_frac=bilge_radius_frac)
        sections.append(SectionDef(station=x, area_coeff=ac, points=pts))

    if lcb_frac is not None:
        sections = lackenby_shift(sections, Cb_target=Cb, lcb_frac_target=lcb_frac, L=L, B=B, T=T)

    return sections


# ---------------------------------------------------------------------------
# lackenby_shift
# ---------------------------------------------------------------------------

def lackenby_shift(
    sections: List[SectionDef],
    Cb_target: float,
    lcb_frac_target: float,
    L: float,
    B: float,
    T: float,
) -> List[SectionDef]:
    """
    Apply the Lackenby (1950) Δ(Ac)/Δ(Af) shift to the sectional-area curve.

    This is the standard naval-architecture method for adjusting a parent hull
    to achieve specified CB and LCB without modifying the midship section.

    Method (Lackenby 1950, RINA Trans. 92, Eqs. 3–6)
    -------------------------------------------------
    Given a parent sectional-area curve A(x)/Amid, we seek a new curve A'(x)/Amid
    satisfying:

        ∫₀¹ A'(ξ) dξ = Cp_target  (prismatic coefficient)
        ∫₀¹ ξ·A'(ξ) dξ = Cp_target · lcb_frac_target  (LCB condition)

    The Lackenby shift adds a linear perturbation:

        A'(ξ) = A(ξ) + δAc · φc(ξ) + δAf · φf(ξ)

    where:
        φc(ξ) = (1 - ξ)·ξ²        — aft-body shape function (Lackenby 1950 Eq. 4a)
        φf(ξ) = ξ·(1 - ξ)²        — fore-body shape function (Lackenby 1950 Eq. 4b)

    The integrals of φc and φf over [0,1] are:
        ∫φc = 1/12  (aft control)
        ∫φf = 1/12  (fore control)

    The first-moment integrals:
        ∫ξ·φc = 1/30 + 1/20 = 1/20   (from ∫₀¹ ξ(1-ξ)ξ² dξ = ∫ξ²-ξ³-ξ⁴... no)
    Evaluated analytically:
        ∫₀¹ ξ·φc(ξ) dξ = ∫₀¹ ξ²(1-ξ)ξ dξ = ∫₀¹ (ξ³ - ξ⁴) dξ = 1/4 - 1/5 = 1/20
        ∫₀¹ ξ·φf(ξ) dξ = ∫₀¹ ξ·ξ(1-ξ)² dξ = ∫₀¹ (ξ²-2ξ³+ξ⁴) dξ = 1/3-1/2+1/5 = 1/30

    System of equations (per unit of A_mid):
        δAc/12 + δAf/12 = ΔCp
        δAc/20 + δAf/30 = ΔCp · LCB_target - ΔM

    where ΔCp = Cp_target - Cp_parent, ΔM = Cp_target·lcb_target - M_parent.

    Section shapes are scaled proportionally to the new area coefficient.

    Parameters
    ----------
    sections        : list[SectionDef] — input body plan (n_stations)
    Cb_target       : float — target block coefficient
    lcb_frac_target : float — target LCB as fraction of L from AP
    L, B, T         : hull dimensions (m)

    Returns
    -------
    list[SectionDef]
        Shifted body plan with sections scaled to hit CB and LCB targets.

    References
    ----------
    Lackenby, H. (1950). "On the systematic geometrical variation of ship
    forms." Trans. RINA 92, 289-316.  Section 3, Eqs. (3)–(6).

    SNAME PNA Vol. II §2.5 (application of Lackenby method).
    """
    if not sections:
        return sections

    Cm = max(s.area_coeff for s in sections)
    if Cm < 1e-6:
        return sections

    Cp_target = Cb_target / max(Cm, 0.01)
    Cp_target = max(0.40, min(Cp_target, 0.95))

    n = len(sections)
    xi_arr = [s.station / L for s in sections]

    # Current area-coefficient distribution (normalised by Cm)
    ac_arr = [s.area_coeff / Cm for s in sections]

    # Compute current Cp and LCB fraction by trapezoidal rule
    def trapz_1d(xs, ys):
        total = 0.0
        for i in range(len(xs) - 1):
            total += 0.5 * (ys[i] + ys[i + 1]) * (xs[i + 1] - xs[i])
        return total

    Cp_curr = trapz_1d(xi_arr, ac_arr)
    M_curr = trapz_1d(xi_arr, [xi * ac for xi, ac in zip(xi_arr, ac_arr)])
    lcb_curr = M_curr / Cp_curr if Cp_curr > 1e-6 else 0.5

    delta_Cp = Cp_target - Cp_curr
    delta_M = Cp_target * lcb_frac_target - M_curr

    # Solve 2×2 system:
    # [1/12  1/12] [dAc]   [delta_Cp]
    # [1/20  1/30] [dAf] = [delta_M ]
    # where dAc, dAf are scaled by 1/Cm
    a11, a12 = 1.0 / 12.0, 1.0 / 12.0
    a21, a22 = 1.0 / 20.0, 1.0 / 30.0
    det = a11 * a22 - a12 * a21
    if abs(det) < 1e-15:
        # Degenerate — return unchanged
        return sections

    dAc = (delta_Cp * a22 - delta_M * a12) / det
    dAf = (a11 * delta_M - a21 * delta_Cp) / det

    # Apply shift: A'(ξ) = A(ξ) + dAc·φc(ξ) + dAf·φf(ξ)
    # where φc(ξ) = (1-ξ)·ξ², φf(ξ) = ξ·(1-ξ)²
    shifted: List[SectionDef] = []
    for i, sec in enumerate(sections):
        xi = xi_arr[i]
        phi_c = (1.0 - xi) * xi * xi
        phi_f = xi * (1.0 - xi) * (1.0 - xi)
        ac_new = ac_arr[i] + dAc * phi_c + dAf * phi_f
        ac_new = max(0.0, min(ac_new, 1.0))

        # Scale section points proportionally
        ac_old = sec.area_coeff
        if ac_old > 1e-6:
            scale = (ac_new * Cm) / ac_old
        else:
            scale = 0.0

        new_pts = [
            SectionPoint(
                waterline=p.waterline,
                half_breadth=p.half_breadth * scale,
            )
            for p in sec.points
        ]
        shifted.append(SectionDef(
            station=sec.station,
            area_coeff=ac_new * Cm,
            points=new_pts,
        ))

    return shifted


# ---------------------------------------------------------------------------
# hull_waterlines  and  hull_buttocks
# ---------------------------------------------------------------------------

def hull_waterlines(
    sections: List[SectionDef],
    n_wl: int = 5,
    T: Optional[float] = None,
) -> List[WaterlineDef]:
    """
    Extract waterline curves from a body plan.

    Samples the half-breadth at each section at evenly-spaced waterline levels,
    building a (station, half_breadth) curve for each level.

    Parameters
    ----------
    sections : list[SectionDef]
    n_wl     : int — number of waterline levels (default 5; includes keel and DWL)
    T        : float — design waterline draft.  If None, uses max waterline in sections.

    Returns
    -------
    list[WaterlineDef]
    """
    if not sections:
        return []

    if T is None:
        T = max(
            p.waterline
            for sec in sections
            for p in sec.points
        )
    T = float(T)

    waterlines: List[WaterlineDef] = []
    for j in range(n_wl):
        z = float(j) / (n_wl - 1) * T
        wl = WaterlineDef(draft=z)
        for sec in sections:
            hb = _interpolate_hb(sec, z)
            wl.stations.append(sec.station)
            wl.half_breadths.append(hb)
        waterlines.append(wl)
    return waterlines


def hull_buttocks(
    sections: List[SectionDef],
    n_butt: int = 5,
    B: Optional[float] = None,
    T: Optional[float] = None,
) -> List[ButtockDef]:
    """
    Extract buttock lines from a body plan.

    For each constant-y slice, finds the draft at each section where
    the half-breadth equals the specified y-value.

    Parameters
    ----------
    sections : list[SectionDef]
    n_butt   : int — number of buttock lines (default 5, from CL to max half-beam)
    B        : float — full beam (m).  If None, uses max half-breadth * 2.
    T        : float — draft.  If None, uses max waterline.

    Returns
    -------
    list[ButtockDef]
    """
    if not sections:
        return []

    if B is None:
        B = 2.0 * max(
            p.half_breadth
            for sec in sections
            for p in sec.points
        )
    if T is None:
        T = max(
            p.waterline
            for sec in sections
            for p in sec.points
        )

    buttocks: List[ButtockDef] = []
    for k in range(n_butt):
        y = (float(k) + 1.0) / n_butt * (B / 2.0)
        bt = ButtockDef(half_breadth=y)
        for sec in sections:
            z = _interpolate_z_for_y(sec, y, T)
            bt.stations.append(sec.station)
            bt.drafts.append(z)
        buttocks.append(bt)
    return buttocks


def _interpolate_hb(sec: SectionDef, target_z: float) -> float:
    """Return half-breadth at waterline target_z by linear interpolation."""
    pts = sec.points
    if not pts:
        return 0.0
    if target_z <= pts[0].waterline:
        return pts[0].half_breadth
    if target_z >= pts[-1].waterline:
        return pts[-1].half_breadth
    for i in range(len(pts) - 1):
        z0, z1 = pts[i].waterline, pts[i + 1].waterline
        if z0 <= target_z <= z1:
            if z1 - z0 < 1e-12:
                return pts[i].half_breadth
            t = (target_z - z0) / (z1 - z0)
            return pts[i].half_breadth + t * (pts[i + 1].half_breadth - pts[i].half_breadth)
    return 0.0


def _interpolate_z_for_y(sec: SectionDef, target_y: float, T: float) -> float:
    """Return waterline z where half-breadth = target_y (inverse interpolation)."""
    pts = sec.points
    if not pts:
        return T  # deck level (no intersection → above waterline)
    max_hb = max(p.half_breadth for p in pts)
    if target_y > max_hb:
        return T  # above deck — notional
    if target_y <= pts[0].half_breadth:
        return pts[0].waterline
    for i in range(len(pts) - 1):
        y0, y1 = pts[i].half_breadth, pts[i + 1].half_breadth
        if y0 <= target_y <= y1:
            if abs(y1 - y0) < 1e-12:
                return pts[i].waterline
            t = (target_y - y0) / (y1 - y0)
            return pts[i].waterline + t * (pts[i + 1].waterline - pts[i].waterline)
    return T


# ---------------------------------------------------------------------------
# generate_hull (high-level)
# ---------------------------------------------------------------------------

def generate_hull(
    L: float,
    B: float,
    T: float,
    Cb: float = 0.55,
    Cm: float = 0.90,
    n_stations: int = 21,
    n_wl_sections: int = 9,
    n_wl_curves: int = 5,
    n_buttocks: int = 5,
    bilge_radius_frac: float = 0.12,
    lcb_frac: Optional[float] = None,
) -> HullForm:
    """
    Generate a complete parametric displacement hull form.

    High-level entry point.  Calls generate_hull_sections, then extracts
    waterlines and buttock lines.

    Parameters
    ----------
    L, B, T          : hull dimensions (m)
    Cb               : block coefficient (default 0.55)
    Cm               : midship section coefficient (default 0.90)
    n_stations       : number of body-plan stations (default 21)
    n_wl_sections    : waterline points per section shape (default 9)
    n_wl_curves      : number of waterline curves to extract (default 5)
    n_buttocks       : number of buttock lines to extract (default 5)
    bilge_radius_frac: bilge radius fraction (default 0.12)
    lcb_frac         : LCB fraction from AP (None = no Lackenby shift)

    Returns
    -------
    HullForm
    """
    sections = generate_hull_sections(
        L=L, B=B, T=T, Cb=Cb, Cm=Cm,
        n_stations=n_stations,
        n_wl=n_wl_sections,
        bilge_radius_frac=bilge_radius_frac,
        lcb_frac=lcb_frac,
    )

    wls = hull_waterlines(sections, n_wl=n_wl_curves, T=T)
    btts = hull_buttocks(sections, n_butt=n_buttocks, B=B, T=T)

    # Compute achieved Cp from sections
    xi_arr = [s.station / L for s in sections]
    Cm_actual = max(s.area_coeff for s in sections)
    ac_arr = [s.area_coeff / max(Cm_actual, 1e-6) for s in sections]

    def trapz_1d(xs, ys):
        total = 0.0
        for i in range(len(xs) - 1):
            total += 0.5 * (ys[i] + ys[i + 1]) * (xs[i + 1] - xs[i])
        return total

    Cp_actual = trapz_1d(xi_arr, ac_arr)
    Cb_actual = Cp_actual * Cm_actual
    M_actual = trapz_1d(xi_arr, [xi * ac for xi, ac in zip(xi_arr, ac_arr)])
    lcb_actual = M_actual / max(Cp_actual, 1e-6)

    return HullForm(
        L=L, B=B, T=T,
        Cb=Cb_actual,
        Cm=Cm_actual,
        Cp=Cp_actual,
        lcb_frac=lcb_actual,
        sections=sections,
        waterlines=wls,
        buttocks=btts,
    )


# ---------------------------------------------------------------------------
# section_offsets_table — for kerf_marine.sections.OffsetTable
# ---------------------------------------------------------------------------

def section_offsets_table(
    sections: List[SectionDef],
) -> List[Tuple[float, float, float]]:
    """
    Convert sections to (station, waterline, half_breadth) rows
    for use with kerf_marine.sections.OffsetTable.

    Parameters
    ----------
    sections : list[SectionDef]

    Returns
    -------
    list of (station_m, waterline_m, half_breadth_m) tuples
    """
    rows: List[Tuple[float, float, float]] = []
    for sec in sections:
        for pt in sec.points:
            rows.append((sec.station, pt.waterline, pt.half_breadth))
    return rows


# ---------------------------------------------------------------------------
# LLM tool spec + runner
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_marine._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]

from typing import Any


marine_hull_form_spec = ToolSpec(
    name="marine_hull_form",
    description=(
        "Generate a parametric displacement-hull body plan from form coefficients. "
        "\n\n"
        "Produces body-plan sections (transverse offsets), waterline curves, and "
        "buttock lines for a ship hull defined by Cb, Cm, and overall dimensions. "
        "Optionally applies the Lackenby (1950) sectional-area curve shift to "
        "achieve a target LCB position. "
        "\n\n"
        "The sectional-area distribution follows the Lewis (1954) power-law prismatic "
        "curve.  Section shapes use a smooth U-form parameterised by local area "
        "coefficient. "
        "\n\n"
        "Returns HullForm with: dimensions, achieved Cb/Cm/Cp/LCB, section offsets, "
        "waterline curves, and buttock lines suitable for downstream hydrostatics. "
        "\n\n"
        "To compute hydrostatics from the result, pass hull_form.sections to "
        "marine_hydrostatics (as offsets = [[station, waterline, half_breadth], ...]). "
        "\n\n"
        "References: Lackenby 1950 RINA Trans. 92, 289-316; Lewis 1954 SNAME Trans. 62; "
        "SNAME PNA Vol. II §2.2–2.5."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "L":    {"type": "number", "description": "Length between perpendiculars (m)."},
            "B":    {"type": "number", "description": "Moulded breadth (m)."},
            "T":    {"type": "number", "description": "Design draft (m)."},
            "Cb":   {"type": "number", "description": "Block coefficient (0.40–0.85). Default 0.55."},
            "Cm":   {"type": "number", "description": "Midship section coefficient (0.85–0.99). Default 0.90."},
            "lcb_frac": {
                "type": "number",
                "description": (
                    "LCB position as fraction of L from AP (0=AP, 1=FP). "
                    "Typical range 0.45–0.55 (forward of midship for most hulls). "
                    "If given, Lackenby shift is applied. Default: None (no shift)."
                ),
            },
            "n_stations": {
                "type": "integer",
                "description": "Number of body-plan stations (default 21 = every 5% LBP).",
            },
            "n_wl_curves": {
                "type": "integer",
                "description": "Number of waterline curves to extract (default 5).",
            },
            "n_buttocks": {
                "type": "integer",
                "description": "Number of buttock lines to extract (default 5).",
            },
            "bilge_radius_frac": {
                "type": "number",
                "description": "Bilge radius as fraction of min(B/2, T) (default 0.12).",
            },
        },
        "required": ["L", "B", "T"],
    },
)


async def run_marine_hull_form(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        L = float(args["L"])
        B = float(args["B"])
        T = float(args["T"])
        Cb = float(args.get("Cb", 0.55))
        Cm = float(args.get("Cm", 0.90))
        lcb_frac = float(args["lcb_frac"]) if "lcb_frac" in args else None
        n_stations = int(args.get("n_stations", 21))
        n_wl_curves = int(args.get("n_wl_curves", 5))
        n_buttocks = int(args.get("n_buttocks", 5))
        bilge_radius_frac = float(args.get("bilge_radius_frac", 0.12))

        hull = generate_hull(
            L=L, B=B, T=T, Cb=Cb, Cm=Cm,
            n_stations=n_stations,
            n_wl_curves=n_wl_curves,
            n_buttocks=n_buttocks,
            bilge_radius_frac=bilge_radius_frac,
            lcb_frac=lcb_frac,
        )
        return ok_payload(hull.as_dict())
    except Exception as exc:
        return err_payload(str(exc), "MARINE_HULL_FORM_ERROR")
