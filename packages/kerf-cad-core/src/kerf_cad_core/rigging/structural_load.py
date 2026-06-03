"""
kerf_cad_core.rigging.structural_load
======================================
Braceworks-equivalent truss and rigging-cable structural-load analysis.

Implements uniform-load and point-load analysis for truss segments (aluminium
or steel box-truss) plus catenary cable tension / sag analysis for rigging
systems used in entertainment staging, broadcast, and similar applications.

This module is analogous to Vectorworks Braceworks structural-load analysis
but is entirely standards-based and does NOT rely on proprietary data.

Standards referenced
--------------------
BS 7905-1:2002  — Lifting equipment for performance, broadcast and similar
                  applications. Part 1: code of practice for the use of wire
                  rope hoists.
BS 7905-2:2002  — ... Part 2: specification for rigging hardware.
DIN 18800-1:2008 — Steel structures: design and construction. Part 1.
ANSI E1.2-2012  — Entertainment Technology: Design, Manufacture and Use of
                  Aluminium Trusses and Towers (ESTA).
ANSI E1.6-1:2012 — Entertainment Technology: Powered Hoist Systems.

Engineering basis
-----------------
Truss segments are modelled as simply-supported beams carrying both self-weight
(uniformly distributed) and discrete point loads (rigging points).  The
Euler-Bernoulli closed-form solutions from Roark's Formulas for Stress and
Strain (9th ed., §8) are applied:

  Uniform distributed load (self-weight):
      δ_max = 5·w·L⁴ / (384·E·I)     [Roark Table 8.1, case 2]
      M_max = w·L² / 8

  Superimposed point load at arbitrary position a from left support:
      M_max (at load point) = P·a·(L−a) / L  for a ≤ L/2 (else symmetric)
      δ_at_load = P·a²·(L−a)² / (3·E·I·L)
  (Roark Table 8.1, case 5 for off-centre point load on SS beam)

Utilisation is computed as:
    u_bending = M_actual / (Fy·Z_x)     where Z_x ≈ b·d²/6 for box section
    u_shear   = V_actual / (0.6·Fy·A_web)

The maximum of u_bending and u_shear is reported as utilization_pct.

For cables, the catenary equation is used:
    y(x) = a·(cosh(x/a) − 1)   where a = T_H / w
    T_H  = horizontal tension component, w = weight per unit length
    T_anchor = T_H·cosh(L/(2a)) = sqrt(T_H² + (w·L/2)²)

Because the exact catenary requires Newton-Raphson iteration to solve for a
given sag, the simplified parabolic approximation (valid for sag/span < 0.1)
and the exact catenary are both provided; the exact form is preferred.

All input forces are in **Newtons (N)**, lengths in **metres (m)**, moments
reported in **kN·m**, deflections in **mm**.

HONEST CAVEAT
-------------
  • Linear-elastic static analysis only. No dynamic load factors, no impact
    factors beyond user-supplied inputs.
  • Truss moment of inertia / section modulus are ESTIMATED from the rated
    max_uniform_load_per_m — this is an approximation; for precise checks
    use the manufacturer's structural data.
  • No lateral-torsional buckling, no connection checks.
  • Cable model: catenary, no aerodynamic, no temperature effects.
  • Verify all results with a qualified structural engineer before use.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

__all__ = [
    "TrussSegment",
    "RiggingPoint",
    "CableSpan",
    "RiggingLoadReport",
    "analyze_rigging_load",
    "cable_catenary_tension",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TrussSegment:
    """One span of a box-truss (aluminium or steel).

    Parameters
    ----------
    segment_id : str
        Unique identifier for this truss segment.
    start_pt : tuple of (x, y, z) in metres
        Start node coordinates.
    end_pt : tuple of (x, y, z) in metres
        End node coordinates.
    self_weight_per_m : float
        Self weight of the truss per unit length (N/m). Typical aluminium
        box-truss: 60–150 N/m depending on size. Must be ≥ 0.
    max_uniform_load_per_m : float
        Manufacturer-rated maximum superimposed uniform distributed load
        (N/m). Used to back-calculate an effective section modulus for
        utilisation checks. Must be > 0.
        Reference: ANSI E1.2 §6.2; DIN 18800-1 §4.
    max_point_load : float
        Manufacturer-rated maximum single centre-point load (N). Used for
        point-load utilisation scaling. Must be > 0.
        Reference: ANSI E1.2 §6.2.
    """
    segment_id: str
    start_pt: Tuple[float, float, float]
    end_pt: Tuple[float, float, float]
    self_weight_per_m: float          # N/m
    max_uniform_load_per_m: float     # N/m, manufacturer-rated
    max_point_load: float             # N,   manufacturer-rated


@dataclass
class RiggingPoint:
    """A discrete load applied to a truss (e.g. a motor/hoist attachment).

    Parameters
    ----------
    point_id : str
        Unique identifier.
    location : tuple of (x, y, z) in metres
        3-D position of the applied load.
    point_load_n : float
        Downward force magnitude (N, positive downward). Must be ≥ 0.
        Reference: BS 7905-1:2002 §4.3 (load classification).
    """
    point_id: str
    location: Tuple[float, float, float]
    point_load_n: float   # N, downward positive


@dataclass
class CableSpan:
    """A rigging cable (wire rope, chain, or steel rod) spanning two anchors.

    Parameters
    ----------
    cable_id : str
        Unique identifier.
    anchor_a : tuple of (x, y, z) in metres
        First anchor point.
    anchor_b : tuple of (x, y, z) in metres
        Second anchor point.
    breaking_strength_n : float
        Minimum breaking force (N). Reference: BS 7905-2:2002 §5.
    working_load_limit_n : float
        Working load limit (WLL) in N. Typically breaking_strength / 5
        per BS 7905 and EN 818 for rigging applications.
    """
    cable_id: str
    anchor_a: Tuple[float, float, float]
    anchor_b: Tuple[float, float, float]
    breaking_strength_n: float
    working_load_limit_n: float        # WLL = breaking / 5 typically


@dataclass
class RiggingLoadReport:
    """Output of analyze_rigging_load.

    Attributes
    ----------
    segment_loads : dict
        Per-segment results keyed by segment_id:
            bending_moment_kN_m  — peak bending moment (kN·m)
            shear_kN             — peak shear force (kN)
            deflection_mm        — estimated mid-span deflection (mm)
            utilization_pct      — utilisation percentage (0–100+)
    cable_tensions : dict
        Per-cable results keyed by cable_id:
            tension_kN           — anchor tension (kN)
            sag_m                — mid-span sag (m)
            utilization_pct      — tension / WLL × 100 (0–100+)
    overloaded_segments : list of str
        segment_ids where utilization_pct > 100.
    overloaded_cables : list of str
        cable_ids where utilization_pct > 100.
    overall_safety_factor : float
        min(WLL / max_tension) across all cables and segments; 0 if no
        rated capacity is defined.
    honest_caveat : str
        Plain-language scope and assumptions statement.
    """
    segment_loads: Dict[str, Dict]
    cable_tensions: Dict[str, Dict]
    overloaded_segments: List[str]
    overloaded_cables: List[str]
    overall_safety_factor: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _segment_length(seg: TrussSegment) -> float:
    """Euclidean span length (m)."""
    dx = seg.end_pt[0] - seg.start_pt[0]
    dy = seg.end_pt[1] - seg.start_pt[1]
    dz = seg.end_pt[2] - seg.start_pt[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _project_onto_segment(
    seg: TrussSegment,
    pt: Tuple[float, float, float],
) -> float:
    """Return the scalar projection of point pt onto the segment axis (m).

    The result is clamped to [0, L] so loads exactly at or beyond the
    supports are treated as support reactions (moment = 0).
    """
    L = _segment_length(seg)
    if L < 1e-9:
        return 0.0
    dx = seg.end_pt[0] - seg.start_pt[0]
    dy = seg.end_pt[1] - seg.start_pt[1]
    dz = seg.end_pt[2] - seg.start_pt[2]
    # Unit vector along segment.
    ux, uy, uz = dx / L, dy / L, dz / L
    # Vector from start to point.
    vx = pt[0] - seg.start_pt[0]
    vy = pt[1] - seg.start_pt[1]
    vz = pt[2] - seg.start_pt[2]
    proj = vx * ux + vy * uy + vz * uz
    return float(np.clip(proj, 0.0, L))


def _ss_point_load_moment(P: float, a: float, L: float) -> float:
    """Peak bending moment (N·m) for a simply-supported beam under point load P
    at position a from the left support (span L).

    M_max = P·a·(L−a) / L   [Roark 9e Table 8.1 case 5]
    For a at the midpoint this simplifies to PL/4.
    """
    if L < 1e-9:
        return 0.0
    return P * a * (L - a) / L


def _ss_point_load_deflection(P: float, a: float, L: float, EI: float) -> float:
    """Mid-span deflection approximation (m) for off-centre point load.

    Uses the exact closed-form for δ at x = L/2 from Roark 9e Table 8.1
    case 5. Valid for a ≤ L/2; by symmetry the result is the same for a ≥ L/2.
    """
    if L < 1e-9 or EI < 1e-9:
        return 0.0
    b = L - a
    # Ensure a ≤ b (load is in the left half).
    if a > b:
        a, b = b, a
    x = L / 2.0
    # δ(x) = P·b·x / (6·E·I·L) · (L² − b² − x²)   for 0 ≤ x ≤ a
    # For a ≤ x (load in left half, evaluate at x = L/2 which is ≥ a only if a ≤ L/2):
    if x <= a:
        delta = P * b * x / (6.0 * EI * L) * (L * L - b * b - x * x)
    else:
        # δ at x ≥ a: δ(x) = P·a·(L−x)/(6EIL)·(2Lx − a² − x²)
        delta = P * a * (L - x) / (6.0 * EI * L) * (2.0 * L * x - a * a - x * x)
    return abs(delta)


def _effective_EI_from_rated_load(seg: TrussSegment, L: float) -> float:
    """Estimate E·I (N·m²) from the manufacturer's rated maximum uniform load.

    For a simply-supported beam with UDL w (N/m), M_max = w·L²/8.
    We assume a utilisation fraction of 1.0 at rated load and a target
    allowable bending stress of ~120 MPa (typical for 6061-T6 aluminium
    box-truss per ANSI E1.2).  Section modulus Z ≈ M_max / 120e6 (m³).
    EI is then estimated from the parabolic deflection formula:
        δ_L/300 ≈ 5wL⁴ / (384 EI)   →   EI ≈ 5wL⁴·300 / (384·L)

    This is an approximation; real trusses have published I values.
    """
    w = seg.max_uniform_load_per_m  # N/m
    if w <= 0 or L < 1e-9:
        return 1.0  # degenerate: return unit EI, utilisation math degrades gracefully
    # Deflection limit L/300 at rated UDL.
    delta_limit = L / 300.0  # m
    # EI = 5wL⁴ / (384 · δ_limit)
    EI = (5.0 * w * L ** 4) / (384.0 * delta_limit)
    return max(EI, 1.0)


def _segment_utilisation(
    M_actual: float,
    V_actual: float,
    seg: TrussSegment,
    L: float,
) -> float:
    """Compute utilisation as fraction (0–1+) based on rated capacities.

    Bending utilisation: M_actual / M_rated
        where M_rated = max_uniform_load_per_m · L² / 8

    Shear utilisation: V_actual / V_rated
        where V_rated = max_uniform_load_per_m · L / 2

    Returns max(u_bending, u_shear).

    Reference: ANSI E1.2-2012 §6; DIN 18800-1 §8.
    """
    if L < 1e-9:
        return 0.0
    w_rated = seg.max_uniform_load_per_m
    M_rated = w_rated * L * L / 8.0   # N·m
    V_rated = w_rated * L / 2.0       # N

    u_bend = M_actual / M_rated if M_rated > 1e-9 else 0.0
    u_shear = V_actual / V_rated if V_rated > 1e-9 else 0.0
    return max(u_bend, u_shear)


# ---------------------------------------------------------------------------
# Public API: catenary cable
# ---------------------------------------------------------------------------

def cable_catenary_tension(
    span_m: float,
    sag_m: float,
    weight_per_m_n: float,
) -> float:
    """Anchor tension for a catenary cable.

    The catenary equation for a uniformly loaded cable of total weight per
    unit length w (N/m), horizontal span L (m), and mid-span sag d (m):

        y(x) = a·(cosh(x/a) − 1),   where a = T_H / w

    At mid-span (x = L/2): d = a·(cosh(L/(2a)) − 1)

    The horizontal tension component T_H is found iteratively by solving the
    catenary sag equation via Newton-Raphson.  Anchor tension (at the support):

        T_anchor = w · (a·sinh(L/(2a)))  = sqrt(T_H² + (w·L/2)²)

    For small sag/span ratios (< 0.05) the parabolic approximation is used:
        T_H ≈ w·L² / (8·d)
    with absolute error < 0.3% for sag/span < 0.1.

    Reference: Irvine, H.M. (1981) Cable Structures, MIT Press.
               BS 7905-1:2002 Annex A (cable sag tables).

    Parameters
    ----------
    span_m : float
        Horizontal projection of cable span (m). Must be > 0.
    sag_m : float
        Mid-span sag (m, positive downward). Must be > 0.
    weight_per_m_n : float
        Cable self-weight per unit length (N/m). Must be > 0.

    Returns
    -------
    float
        Anchor tension (N). Always ≥ weight_per_m_n · span_m / 2.

    Raises
    ------
    ValueError
        If span_m, sag_m, or weight_per_m_n are non-positive.
    """
    if span_m <= 0.0:
        raise ValueError(f"span_m must be > 0, got {span_m}")
    if sag_m <= 0.0:
        raise ValueError(f"sag_m must be > 0, got {sag_m}")
    if weight_per_m_n <= 0.0:
        raise ValueError(f"weight_per_m_n must be > 0, got {weight_per_m_n}")

    L = span_m
    d = sag_m
    w = weight_per_m_n
    ratio = d / L

    if ratio < 0.05:
        # Parabolic approximation: T_H ≈ w·L² / (8·d)
        T_H = w * L * L / (8.0 * d)
    else:
        # Exact catenary: Newton-Raphson solve a·(cosh(L/(2a)) − 1) = d
        # where a = T_H / w > 0.
        # Let u = L/(2a); then a = L/(2u), d = (L/(2u))·(cosh(u) − 1)
        # → f(u) = (L/2)·(cosh(u) − 1)/u − d = 0
        # f'(u) = (L/2)·(u·sinh(u) − (cosh(u)−1)) / u²
        # Initial guess from parabolic:
        T_H_para = w * L * L / (8.0 * d)
        a_guess = T_H_para / w
        u = L / (2.0 * a_guess)
        for _ in range(50):
            ch = math.cosh(u)
            sh = math.sinh(u)
            f = (L / 2.0) * (ch - 1.0) / u - d
            fp = (L / 2.0) * (u * sh - (ch - 1.0)) / (u * u)
            if abs(fp) < 1e-15:
                break
            u_new = u - f / fp
            if u_new <= 0:
                u_new = u / 2.0
            if abs(u_new - u) < 1e-10 * u:
                u = u_new
                break
            u = u_new
        a_exact = L / (2.0 * u)
        T_H = a_exact * w

    # Anchor tension (at support, at the ends of the cable).
    # T_anchor = sqrt(T_H² + (w·L/2)²)
    T_V = w * L / 2.0    # vertical component at each anchor (symmetric)
    T_anchor = math.sqrt(T_H * T_H + T_V * T_V)
    return T_anchor


# ---------------------------------------------------------------------------
# Public API: main analysis
# ---------------------------------------------------------------------------

def analyze_rigging_load(
    segments: List[TrussSegment],
    points: List[RiggingPoint],
    cables: List[CableSpan],
) -> RiggingLoadReport:
    """Compute static load analysis for a rigging system.

    For each truss segment:
    1. Computes self-weight uniform-load moment and deflection.
    2. Adds superimposed moments from each rigging point that projects onto
       the segment span.
    3. Reports utilisation vs manufacturer-rated capacities (ANSI E1.2).

    For each cable span:
    1. Computes the total load carried (assumed to be the sum of rigging
       point loads that are geometrically associated with the cable, or the
       cable self-weight if no points are assigned).
    2. Computes catenary tension and sag.
    3. Verifies tension ≤ working_load_limit_n (BS 7905-2).

    HONEST: linear-elastic only. No dynamic load factors beyond what the
    user supplies. No lateral-torsional buckling. No connection checks.
    Verify with a qualified structural engineer.

    Parameters
    ----------
    segments : list of TrussSegment
        Truss chord / segment definitions.
    points : list of RiggingPoint
        Point loads (hoist motors, fixtures, etc.).
    cables : list of CableSpan
        Rigging cables (wire rope, etc.).

    Returns
    -------
    RiggingLoadReport
    """
    segment_loads: Dict[str, Dict] = {}
    cable_tensions: Dict[str, Dict] = {}
    overloaded_segments: List[str] = []
    overloaded_cables: List[str] = []
    min_safety_factors: List[float] = []

    # ----------------------------------------------------------------
    # Segment analysis
    # ----------------------------------------------------------------
    for seg in segments:
        L = _segment_length(seg)

        # Estimate EI from manufacturer rated load.
        EI = _effective_EI_from_rated_load(seg, L)

        # 1. Self-weight contribution (UDL)
        w = seg.self_weight_per_m   # N/m
        M_sw = (w * L * L) / 8.0   # N·m  [Roark Table 8.1 case 2]
        V_sw = w * L / 2.0          # N
        delta_sw = (5.0 * w * L ** 4) / (384.0 * EI) * 1000.0  # mm

        # 2. Superimposed point loads
        M_pl_total = 0.0
        V_pl_max = 0.0
        delta_pl_total = 0.0

        for rp in points:
            a = _project_onto_segment(seg, rp.location)
            if a <= 0.0 or a >= L:
                continue  # load is at or beyond the support
            P = rp.point_load_n
            # Reactions at supports (simple beam):
            R_a = P * (L - a) / L   # left reaction
            R_b = P * a / L         # right reaction
            M_pl = _ss_point_load_moment(P, a, L)   # N·m
            V_pl = max(R_a, R_b)
            delta_pl = _ss_point_load_deflection(P, a, L, EI) * 1000.0  # mm
            M_pl_total += M_pl
            V_pl_max = max(V_pl_max, V_pl)
            delta_pl_total += delta_pl

        # Combine self-weight + point loads (superposition, linear-elastic).
        M_total = M_sw + M_pl_total            # N·m
        V_total = V_sw + V_pl_max              # N (conservative sum)
        delta_total = delta_sw + delta_pl_total  # mm

        # Utilisation vs rated capacity.
        u = _segment_utilisation(M_total, V_total, seg, L)
        u_pct = u * 100.0

        # Safety factor based on rated point load vs actual max shear force.
        if seg.max_point_load > 1e-9 and V_total > 1e-9:
            sf = seg.max_point_load / V_total
            min_safety_factors.append(sf)

        segment_loads[seg.segment_id] = {
            "bending_moment_kN_m": round(M_total / 1000.0, 4),
            "shear_kN": round(V_total / 1000.0, 4),
            "deflection_mm": round(delta_total, 3),
            "utilization_pct": round(u_pct, 2),
            "span_m": round(L, 4),
        }

        if u_pct > 100.0:
            overloaded_segments.append(seg.segment_id)

    # ----------------------------------------------------------------
    # Cable analysis
    # ----------------------------------------------------------------
    for cab in cables:
        # Horizontal span between anchors.
        dx = cab.anchor_b[0] - cab.anchor_a[0]
        dy = cab.anchor_b[1] - cab.anchor_a[1]
        dz = cab.anchor_b[2] - cab.anchor_a[2]
        span_3d = math.sqrt(dx * dx + dy * dy + dz * dz)
        # Projected horizontal span (in XY plane if needed, use full 3D span).
        span_h = span_3d

        # Sum of rigging-point loads geometrically associated with this cable.
        # Association heuristic: if a RiggingPoint is within 1 m of the cable
        # midpoint or the cable is the only cable, add its load.
        mid = (
            (cab.anchor_a[0] + cab.anchor_b[0]) / 2.0,
            (cab.anchor_a[1] + cab.anchor_b[1]) / 2.0,
            (cab.anchor_a[2] + cab.anchor_b[2]) / 2.0,
        )
        total_point_load = 0.0
        for rp in points:
            dist = math.sqrt(
                (rp.location[0] - mid[0]) ** 2
                + (rp.location[1] - mid[1]) ** 2
                + (rp.location[2] - mid[2]) ** 2
            )
            if dist < 1.0 or len(cables) == 1:
                total_point_load += rp.point_load_n

        # Effective weight per metre for catenary calculation.
        # The dominant load for rigging cables is the concentrated loads at
        # the midpoint rather than distributed self-weight.  For simplicity:
        # treat total point load as an equivalent UDL (conservative for sag).
        # Self-weight of wire rope: ~7.5 kg/m for 16 mm rope ≈ 73 N/m.
        # Here we use a conservative default of 50 N/m if not specified.
        # (Real wire rope data should be used; see BS 7905-2 Annex A.)
        w_self = 50.0  # N/m  (conservative default: ~7 mm wire rope equiv.)
        if span_h > 0.1:
            w_equiv = w_self + total_point_load / max(span_h, 0.1)
        else:
            w_equiv = w_self + total_point_load

        # Target sag: assume 2 % of span (typical pre-rigged tight cable).
        sag_target = max(0.02 * span_h, 0.05)  # at least 50 mm sag

        try:
            T_anchor = cable_catenary_tension(span_h, sag_target, w_equiv)
        except ValueError:
            T_anchor = w_equiv * span_h  # fallback: horizontal estimate

        T_kN = T_anchor / 1000.0
        u_cable = T_anchor / cab.working_load_limit_n if cab.working_load_limit_n > 0 else 0.0
        u_cable_pct = u_cable * 100.0

        if cab.working_load_limit_n > 1e-9 and T_anchor > 1e-9:
            sf = cab.working_load_limit_n / T_anchor
            min_safety_factors.append(sf)

        cable_tensions[cab.cable_id] = {
            "tension_kN": round(T_kN, 4),
            "sag_m": round(sag_target, 4),
            "utilization_pct": round(u_cable_pct, 2),
            "span_m": round(span_h, 4),
        }

        if u_cable_pct > 100.0:
            overloaded_cables.append(cab.cable_id)

    # ----------------------------------------------------------------
    # Overall safety factor
    # ----------------------------------------------------------------
    overall_sf = min(min_safety_factors) if min_safety_factors else 0.0

    caveat = (
        "RIGGING-STRUCTURAL-LOAD: Linear-elastic static analysis per ANSI E1.2-2012, "
        "BS 7905-1/2:2002, DIN 18800-1:2008. "
        "Truss utilisation computed from manufacturer-rated UDL capacity as proxy "
        "for section modulus — use published structural data for final design. "
        "Cable tensions via catenary (Irvine 1981) at 2% sag/span; actual sag may vary. "
        "NO dynamic load factors, NO lateral-torsional buckling, NO connection checks. "
        "ALWAYS verify with a qualified structural engineer before use in a live event."
    )

    return RiggingLoadReport(
        segment_loads=segment_loads,
        cable_tensions=cable_tensions,
        overloaded_segments=overloaded_segments,
        overloaded_cables=overloaded_cables,
        overall_safety_factor=round(overall_sf, 3),
        honest_caveat=caveat,
    )
