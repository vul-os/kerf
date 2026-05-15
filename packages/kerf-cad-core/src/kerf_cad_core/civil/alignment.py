"""
kerf_cad_core.civil.alignment — Road alignment geometry (horizontal + vertical).

Horizontal alignment
--------------------
A tangent–circular-curve–tangent (TCT) alignment with optional Euler spiral
(clothoid) transition curves.  Geometry follows AASHTO "A Policy on Geometric
Design of Highways and Streets" (the Green Book), §3.

Key relations:
  Δ  = intersection (deflection) angle between back-tangent and forward tangent
  R  = radius of circular curve (metres)
  L  = arc length of circular curve = R·Δ  (Δ in radians)
  T  = tangent length from PI to PC = R·tan(Δ/2)
  E  = external distance            = R·(sec(Δ/2) - 1)
  M  = middle ordinate              = R·(1 - cos(Δ/2))
  C  = long chord from PC to PT     = 2·R·sin(Δ/2)
  PC = Point of Curvature  (tangent-to-curve)
  PT = Point of Tangency   (curve-to-tangent)
  PI = Point of Intersection of tangents

Stationing:  station expressed as integer + decimal, e.g. 12+34.56.
  sta_PT = sta_PC + L

Spiral (clothoid) transition:
  Ls = spiral length (metres)
  A² = Ls·R  (clothoid parameter)
  θs = Ls / (2·R)  (spiral angle, radians)
  TS = tangent-to-spiral point; SC = spiral-to-circle; CS = circle-to-spiral; ST = spiral-to-tangent
  Short-tangent = Ls/3, Long-tangent ≈ 2·Ls/3  (approximation)
  Shifted PC radius: Rs_x ≈ Ls²/(6·R), Rs_y ≈ Ls⁴/(40·R³)

Superelevation hint (AASHTO e+f method):
  v²
  ── = e + f     (v in m/s, R in metres)
  gR
  where g = 9.80665 m/s²
        e = superelevation rate (decimal)
        f = side-friction factor (AASHTO Table 3-7 conservative average)
  Solved for e, clamped to [0, e_max=0.12] per AASHTO highway design.

Vertical alignment
------------------
Parabolic crest or sag curves connecting two tangent grades.

  G1, G2 = tangent grades (decimal, e.g. 0.04 = 4%)
  A  = |G2 - G1|  (algebraic difference, used for K-value)
  L  = curve length (metres)
  K  = L / A      (rate of vertical curvature; AASHTO Table 3-34/35)
  PVC = start of vertical curve
  PVI = point of vertical intersection
  PVT = end of vertical curve
  Elevation at any point x from PVC:
      e(x) = e_PVC + G1·x + (G2-G1)/(2·L)·x²

  High/low point (only when G1 and G2 have opposite signs):
      x_hl = -G1·L / (G2-G1)
      sta_hl = sta_PVC + x_hl

  Sight-distance check (AASHTO):
      Crest K_min for SSD = S²/(404+3.5·S) when S ≤ L  (stopping S in metres)
      Sag  K_min for SSD  = S²/(120+3.5·S) when S ≤ L
      Simplified AASHTO headlight formula for sag curves.

Units: metres, decimal grades, km/h design speed.
Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_G = 9.80665  # gravitational acceleration m/s²
_E_MAX = 0.12  # max superelevation per AASHTO (highway, no snow)
_KMH_TO_MS = 1.0 / 3.6

# AASHTO Table 3-7 conservative side-friction factors by design speed (km/h)
# Source: AASHTO Green Book Table 3-7 (2011 ed.)
_FRICTION_TABLE: list[tuple[float, float]] = [
    (20.0, 0.35),
    (30.0, 0.28),
    (40.0, 0.23),
    (50.0, 0.19),
    (60.0, 0.17),
    (70.0, 0.15),
    (80.0, 0.14),
    (90.0, 0.13),
    (100.0, 0.12),
    (110.0, 0.11),
    (120.0, 0.09),
    (130.0, 0.08),
]


def _side_friction(design_speed_kmh: float) -> float:
    """
    Interpolated AASHTO side-friction factor f for the given design speed.
    Clamps to the table endpoints for speeds outside [20, 130] km/h.
    """
    if design_speed_kmh <= _FRICTION_TABLE[0][0]:
        return _FRICTION_TABLE[0][1]
    if design_speed_kmh >= _FRICTION_TABLE[-1][0]:
        return _FRICTION_TABLE[-1][1]
    for i in range(len(_FRICTION_TABLE) - 1):
        v0, f0 = _FRICTION_TABLE[i]
        v1, f1 = _FRICTION_TABLE[i + 1]
        if v0 <= design_speed_kmh <= v1:
            t = (design_speed_kmh - v0) / (v1 - v0)
            return f0 + t * (f1 - f0)
    return _FRICTION_TABLE[-1][1]


# ---------------------------------------------------------------------------
# Stationing helpers
# ---------------------------------------------------------------------------

def parse_station(sta_str: str) -> float:
    """
    Parse a station string "12+34.56" → 1234.56 (metres).
    Also accepts plain float strings "1234.56" → 1234.56.
    Returns NaN on parse failure (never raises).
    """
    sta_str = sta_str.strip()
    if "+" in sta_str:
        parts = sta_str.split("+", 1)
        try:
            major = float(parts[0]) * 100.0
            minor = float(parts[1])
            return major + minor
        except (ValueError, IndexError):
            return float("nan")
    try:
        return float(sta_str)
    except ValueError:
        return float("nan")


def format_station(sta_m: float) -> str:
    """
    Format a station value in metres as "12+34.56".
    Negative stations are formatted as "-0+12.34".
    """
    if math.isnan(sta_m) or math.isinf(sta_m):
        return str(sta_m)
    negative = sta_m < 0
    abs_sta = abs(sta_m)
    major = int(abs_sta // 100)
    minor = abs_sta - major * 100.0
    sign = "-" if negative else ""
    return f"{sign}{major}+{minor:05.2f}"


def station_add(sta_m: float, delta_m: float) -> float:
    """Add delta metres to a station value; returns new station in metres."""
    return sta_m + delta_m


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class HorizontalCurveResult:
    """
    Geometry of a simple circular curve (no spirals).
    All lengths in metres; angles in degrees.
    """
    ok: bool
    # inputs
    radius_m: float = 0.0
    delta_deg: float = 0.0
    design_speed_kmh: float = 0.0
    # stations
    sta_pi_m: float = 0.0
    sta_pc_m: float = 0.0
    sta_pt_m: float = 0.0
    # geometry
    arc_length_m: float = 0.0
    tangent_length_m: float = 0.0
    external_m: float = 0.0
    middle_ordinate_m: float = 0.0
    long_chord_m: float = 0.0
    degree_of_curve_deg: float = 0.0
    # superelevation
    superelevation: float = 0.0          # e (decimal)
    side_friction: float = 0.0           # f (AASHTO)
    # formatted
    sta_pi: str = ""
    sta_pc: str = ""
    sta_pt: str = ""
    # error
    reason: str = ""


@dataclass
class SpiralCurveResult:
    """
    Geometry of a spiralled alignment: TS–SC–CS–ST.
    """
    ok: bool
    radius_m: float = 0.0
    spiral_length_m: float = 0.0
    delta_deg: float = 0.0
    # spiral geometry
    spiral_angle_deg: float = 0.0
    p_shift_m: float = 0.0              # radial shift of circular curve
    k_tangent_offset_m: float = 0.0    # tangent projection offset
    ts_tangent_length_m: float = 0.0   # tangent from PI to TS
    # arc
    circular_arc_length_m: float = 0.0
    # stations (raw metres)
    sta_ts_m: float = 0.0
    sta_sc_m: float = 0.0
    sta_cs_m: float = 0.0
    sta_st_m: float = 0.0
    # formatted
    sta_ts: str = ""
    sta_sc: str = ""
    sta_cs: str = ""
    sta_st: str = ""
    reason: str = ""


@dataclass
class VerticalCurveResult:
    """
    Geometry of a parabolic vertical curve.
    Elevations in metres; stations in metres.
    """
    ok: bool
    grade1: float = 0.0                 # G1 (decimal)
    grade2: float = 0.0                 # G2 (decimal)
    curve_length_m: float = 0.0
    k_value: float = 0.0                # L/A
    curve_type: str = ""                # "CREST" | "SAG" | "TANGENT"
    # stations (raw metres)
    sta_pvc_m: float = 0.0
    sta_pvi_m: float = 0.0
    sta_pvt_m: float = 0.0
    # elevations
    elev_pvc_m: float = 0.0
    elev_pvi_m: float = 0.0
    elev_pvt_m: float = 0.0
    # high/low point
    has_high_low_point: bool = False
    sta_hl_m: float = 0.0
    elev_hl_m: float = 0.0
    sta_hl: str = ""
    # sight distance
    ssd_check_k_min: float = 0.0        # K_min for ssd (AASHTO)
    ssd_ok: bool = True
    # formatted stations
    sta_pvc: str = ""
    sta_pvi: str = ""
    sta_pvt: str = ""
    reason: str = ""


# ---------------------------------------------------------------------------
# Horizontal — simple circular curve
# ---------------------------------------------------------------------------

def compute_horizontal_curve(
    *,
    delta_deg: float,
    radius_m: float,
    sta_pi_m: float,
    design_speed_kmh: float = 0.0,
) -> HorizontalCurveResult:
    """
    Compute a tangent–circular-curve–tangent horizontal curve.

    Parameters
    ----------
    delta_deg       : Intersection (deflection) angle in degrees (> 0).
    radius_m        : Radius of circular curve in metres (> 0).
    sta_pi_m        : Station of PI in metres.
    design_speed_kmh: Design speed (km/h) for superelevation hint.  0 = skip.

    Returns
    -------
    HorizontalCurveResult  (ok=True on success; ok=False with reason on error)

    AASHTO geometric-design relations used:
      L = R · Δ       (arc length, Δ in radians)
      T = R · tan(Δ/2)
      E = R · (1/cos(Δ/2) - 1)
      M = R · (1 - cos(Δ/2))
      C = 2·R·sin(Δ/2)
      D = 5729.58 / R  (degree of curve, chord definition)
      e = v²/(g·R) - f  clamped [0, e_max]
    """
    if radius_m <= 0:
        return HorizontalCurveResult(
            ok=False,
            reason=f"radius must be > 0; got {radius_m}"
        )
    if delta_deg <= 0:
        return HorizontalCurveResult(
            ok=False,
            reason=f"delta (deflection angle) must be > 0 degrees; got {delta_deg}"
        )
    if delta_deg >= 360:
        return HorizontalCurveResult(
            ok=False,
            reason=f"delta must be < 360 degrees; got {delta_deg}"
        )
    if design_speed_kmh < 0:
        return HorizontalCurveResult(
            ok=False,
            reason=f"design_speed_kmh must be >= 0; got {design_speed_kmh}"
        )

    delta_rad = math.radians(delta_deg)
    half_delta = delta_rad / 2.0

    arc_len = radius_m * delta_rad
    tangent = radius_m * math.tan(half_delta)
    external = radius_m * (1.0 / math.cos(half_delta) - 1.0)
    middle_ord = radius_m * (1.0 - math.cos(half_delta))
    chord = 2.0 * radius_m * math.sin(half_delta)
    # Degree of curve (chord definition): D = 5729.578 / R
    degree_of_curve = 5729.578 / radius_m

    sta_pc = sta_pi_m - tangent
    sta_pt = sta_pc + arc_len

    # Superelevation (AASHTO e + f)
    e_val = 0.0
    f_val = 0.0
    if design_speed_kmh > 0:
        v_ms = design_speed_kmh * _KMH_TO_MS
        f_val = _side_friction(design_speed_kmh)
        e_val = v_ms ** 2 / (_G * radius_m) - f_val
        e_val = max(0.0, min(e_val, _E_MAX))

    return HorizontalCurveResult(
        ok=True,
        radius_m=radius_m,
        delta_deg=delta_deg,
        design_speed_kmh=design_speed_kmh,
        sta_pi_m=sta_pi_m,
        sta_pc_m=sta_pc,
        sta_pt_m=sta_pt,
        arc_length_m=arc_len,
        tangent_length_m=tangent,
        external_m=external,
        middle_ordinate_m=middle_ord,
        long_chord_m=chord,
        degree_of_curve_deg=degree_of_curve,
        superelevation=round(e_val, 6),
        side_friction=round(f_val, 6),
        sta_pi=format_station(sta_pi_m),
        sta_pc=format_station(sta_pc),
        sta_pt=format_station(sta_pt),
    )


# ---------------------------------------------------------------------------
# Horizontal — spiralled (clothoid) curve
# ---------------------------------------------------------------------------

def compute_spiral_curve(
    *,
    delta_deg: float,
    radius_m: float,
    spiral_length_m: float,
    sta_pi_m: float,
) -> SpiralCurveResult:
    """
    Compute a spiralled alignment with clothoid (Euler spiral) transitions.

    Spiral geometry (AASHTO / Hickerson):
      θs = Ls / (2·R)                  (spiral angle, radians)
      p  = Ls²/(24·R)                  (p-shift, radial offset of circular curve)
      k  = Ls/2 - Ls³/(240·R²)        (tangent offset)
      Ts = (R+p)·tan(Δ/2) + k         (tangent length PI to TS)
      Lc = R·(Δ - 2·θs)               (length of circular arc between spirals)

    Parameters
    ----------
    delta_deg      : Deflection angle at PI (degrees).
    radius_m       : Radius of circular curve (metres, > 0).
    spiral_length_m: Length of each transition spiral (metres, > 0).
    sta_pi_m       : Station of PI in metres.
    """
    if radius_m <= 0:
        return SpiralCurveResult(ok=False, reason=f"radius must be > 0; got {radius_m}")
    if spiral_length_m <= 0:
        return SpiralCurveResult(ok=False, reason=f"spiral_length must be > 0; got {spiral_length_m}")
    if delta_deg <= 0:
        return SpiralCurveResult(ok=False, reason=f"delta must be > 0; got {delta_deg}")
    if delta_deg >= 360:
        return SpiralCurveResult(ok=False, reason=f"delta must be < 360; got {delta_deg}")

    delta_rad = math.radians(delta_deg)
    theta_s = spiral_length_m / (2.0 * radius_m)           # spiral angle (rad)

    if 2.0 * theta_s > delta_rad:
        return SpiralCurveResult(
            ok=False,
            reason=(
                f"spiral angle (2·θs={math.degrees(2*theta_s):.2f}°) exceeds "
                f"deflection angle ({delta_deg:.2f}°); reduce spiral_length or increase radius"
            )
        )

    # Clothoid shift terms
    p = spiral_length_m ** 2 / (24.0 * radius_m)
    k = spiral_length_m / 2.0 - spiral_length_m ** 3 / (240.0 * radius_m ** 2)

    # Tangent length from PI to TS
    ts_tangent = (radius_m + p) * math.tan(delta_rad / 2.0) + k

    # Circular arc between spiral-to-circle and circle-to-spiral
    lc = radius_m * (delta_rad - 2.0 * theta_s)

    # Stations
    sta_ts = sta_pi_m - ts_tangent
    sta_sc = sta_ts + spiral_length_m
    sta_cs = sta_sc + lc
    sta_st = sta_cs + spiral_length_m

    return SpiralCurveResult(
        ok=True,
        radius_m=radius_m,
        spiral_length_m=spiral_length_m,
        delta_deg=delta_deg,
        spiral_angle_deg=math.degrees(theta_s),
        p_shift_m=p,
        k_tangent_offset_m=k,
        ts_tangent_length_m=ts_tangent,
        circular_arc_length_m=lc,
        sta_ts_m=sta_ts,
        sta_sc_m=sta_sc,
        sta_cs_m=sta_cs,
        sta_st_m=sta_st,
        sta_ts=format_station(sta_ts),
        sta_sc=format_station(sta_sc),
        sta_cs=format_station(sta_cs),
        sta_st=format_station(sta_st),
    )


# ---------------------------------------------------------------------------
# Vertical — parabolic curve
# ---------------------------------------------------------------------------

def compute_vertical_curve(
    *,
    grade1: float,
    grade2: float,
    sta_pvi_m: float,
    curve_length_m: float,
    elev_pvi_m: float,
    design_speed_kmh: float = 0.0,
    stopping_sight_distance_m: float = 0.0,
) -> VerticalCurveResult:
    """
    Compute a parabolic vertical curve.

    Parameters
    ----------
    grade1                   : Back-tangent grade (decimal, e.g. 0.04 = +4%).
    grade2                   : Forward-tangent grade (decimal).
    sta_pvi_m                : Station of PVI in metres.
    curve_length_m           : Length of vertical curve in metres (> 0).
    elev_pvi_m               : Elevation of PVI in metres.
    design_speed_kmh         : Design speed (km/h); used only with SSD check.
    stopping_sight_distance_m: SSD in metres for sight-distance check (0 = skip).

    Parabolic elevation formula (AASHTO):
      e(x) = e_PVC + G1·x + (G2-G1)/(2·L)·x²   for x ∈ [0, L]

    High/low point (when G1·G2 < 0):
      x_hl = G1·L / (G1 - G2)       [note: equivalent to -G1·L/(G2-G1)]
      sta_hl = sta_PVC + x_hl

    K-value (AASHTO):
      K = L / |G2-G1|  expressed in m/% where A = 100·|G2-G1| is in percent
      For internal computation A is kept as decimal; K = L/A_dec * 0.01
      Conventionally K = L / A  where A = |G2-G1| in % → K = L / (100|G2-G1|)
      Here we use K = L / (100·|G2-G1|) so units are m/%.

    AASHTO SSD sight-distance checks (simplified):
      Crest: K_req = S² / (404 + 3.5·S)   S ≤ L  (S, L in metres)
      Sag:   K_req = S² / (120 + 3.5·S)
    """
    if curve_length_m <= 0:
        return VerticalCurveResult(ok=False, reason=f"curve_length must be > 0; got {curve_length_m}")
    if not math.isfinite(grade1):
        return VerticalCurveResult(ok=False, reason="grade1 must be finite")
    if not math.isfinite(grade2):
        return VerticalCurveResult(ok=False, reason="grade2 must be finite")

    L = curve_length_m
    G1 = grade1
    G2 = grade2

    sta_pvc = sta_pvi_m - L / 2.0
    sta_pvt = sta_pvi_m + L / 2.0

    # Elevations at PVC and PVT from PVI tangent grades
    elev_pvc = elev_pvi_m - G1 * (L / 2.0)
    elev_pvt = elev_pvi_m + G2 * (L / 2.0)

    # Algebraic difference
    A_dec = G2 - G1          # signed
    A_abs_dec = abs(A_dec)   # for K

    # Curve type
    if A_abs_dec < 1e-12:
        curve_type = "TANGENT"
    elif A_dec < 0:
        curve_type = "CREST"
    else:
        curve_type = "SAG"

    # K-value (conventional: K = L / A where A in %)
    A_pct = A_abs_dec * 100.0
    k_value = L / A_pct if A_pct > 1e-12 else float("inf")

    # High/low point
    has_hl = G1 * G2 < 0 and A_abs_dec > 1e-12
    sta_hl_m = 0.0
    elev_hl_m = 0.0
    if has_hl:
        x_hl = G1 * L / (G1 - G2)
        sta_hl_m = sta_pvc + x_hl
        elev_hl_m = elev_pvc + G1 * x_hl + (G2 - G1) / (2.0 * L) * x_hl ** 2

    # Sight-distance check (AASHTO simplified)
    k_min_ssd = 0.0
    ssd_ok = True
    if stopping_sight_distance_m > 0 and A_pct > 1e-12:
        S = stopping_sight_distance_m
        if curve_type == "CREST":
            k_min_ssd = S ** 2 / (404.0 + 3.5 * S)
        elif curve_type == "SAG":
            k_min_ssd = S ** 2 / (120.0 + 3.5 * S)
        ssd_ok = k_value >= k_min_ssd

    return VerticalCurveResult(
        ok=True,
        grade1=G1,
        grade2=G2,
        curve_length_m=L,
        k_value=round(k_value, 4) if math.isfinite(k_value) else float("inf"),
        curve_type=curve_type,
        sta_pvc_m=sta_pvc,
        sta_pvi_m=sta_pvi_m,
        sta_pvt_m=sta_pvt,
        elev_pvc_m=elev_pvc,
        elev_pvi_m=elev_pvi_m,
        elev_pvt_m=elev_pvt,
        has_high_low_point=has_hl,
        sta_hl_m=sta_hl_m,
        elev_hl_m=elev_hl_m,
        sta_hl=format_station(sta_hl_m) if has_hl else "",
        ssd_check_k_min=round(k_min_ssd, 4),
        ssd_ok=ssd_ok,
        sta_pvc=format_station(sta_pvc),
        sta_pvi=format_station(sta_pvi_m),
        sta_pvt=format_station(sta_pvt),
    )


def elevation_at(
    *,
    sta_pvc_m: float,
    elev_pvc_m: float,
    grade1: float,
    grade2: float,
    curve_length_m: float,
    query_sta_m: float,
) -> dict:
    """
    Return the parabolic elevation at an arbitrary station within a vertical curve.

    Parameters
    ----------
    sta_pvc_m     : Station of PVC (metres).
    elev_pvc_m    : Elevation at PVC (metres).
    grade1        : Back-tangent grade (decimal).
    grade2        : Forward-tangent grade (decimal).
    curve_length_m: Curve length (metres, > 0).
    query_sta_m   : Query station in metres.

    Returns {ok, station, elevation_m} or {ok:false, reason}.
    """
    if curve_length_m <= 0:
        return {"ok": False, "reason": f"curve_length must be > 0; got {curve_length_m}"}
    sta_pvt = sta_pvc_m + curve_length_m
    if query_sta_m < sta_pvc_m or query_sta_m > sta_pvt + 1e-9:
        return {
            "ok": False,
            "reason": (
                f"query station {format_station(query_sta_m)} is outside curve "
                f"[{format_station(sta_pvc_m)}, {format_station(sta_pvt)}]"
            ),
        }
    x = query_sta_m - sta_pvc_m
    L = curve_length_m
    elev = elev_pvc_m + grade1 * x + (grade2 - grade1) / (2.0 * L) * x ** 2
    return {
        "ok": True,
        "station": format_station(query_sta_m),
        "elevation_m": round(elev, 6),
    }
