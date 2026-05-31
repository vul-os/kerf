"""
kerf_cad_core.arch.retaining_wall_stability — Cantilever retaining wall stability.

Checks overturning, sliding, and bearing stability of a cantilevered concrete
retaining wall under Rankine active earth pressure.

Geometry convention (per Bowles 5e §12.3 / Das §13):
  H         — total retained height (top of stem to base of footing)
  stem      — vertical concrete stem: thickness t_m, height = H - h_m
  base      — horizontal concrete base: width B_m, thickness h_m
  heel_length — length of heel (behind stem, soil side)
  toe_length  — length of toe (in front of stem)
  B = toe_length + stem_thickness + heel_length

Earth pressure (Rankine active, level backfill, no surcharge):
  Ka = tan²(45 - φ/2)
  Pa = 0.5 · γ_s · H² · Ka         (horizontal resultant, kN/m)
  Acts at H/3 above base of footing

Weight components (per metre of wall length):
  W_stem  = γ_c · t_m · (H - h_m)
  W_base  = γ_c · B_m · h_m
  W_soil  = γ_s · heel_length · (H - h_m)   (soil on heel)

Stability checks:
  FoS_overturning = ΣM_resisting / ΣM_overturning   (about toe; minimum 2.0)
  FoS_sliding     = (ΣW · tan δ) / Pa                (minimum 1.5)
  Bearing:
    e = B/2 − (ΣM_resisting − ΣM_overturning) / ΣW
    q_max = (ΣW / B) · (1 + 6e/B)                   (trapezoidal distribution)
    FoS_bearing = q_a / q_max                         (minimum 3.0)

References:
  Bowles J.E. (1996) Foundation Engineering 5e, §12.3.
  Das B.M. Principles of Geotechnical Engineering §13.

SCOPE LIMITATIONS (see honest_caveat in report):
  - Rankine ACTIVE pressure only (level backfill, cohesionless backfill)
  - No surcharge load
  - No seismic (Mononobe-Okabe) component
  - No passive resistance from soil in front of toe
  - No water table / hydrostatic pressure
  - Cohesionless backfill only (c = 0 assumed)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "RetainingWallSpec",
    "SoilSpec",
    "RetainingWallReport",
    "check_retaining_wall",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RetainingWallSpec:
    """
    Geometry of a cantilevered concrete retaining wall.

    Parameters
    ----------
    wall_height_H_m : float
        Total retained height H from top of stem to bottom of base footing
        (m).  This includes the base thickness.  Must be > 0.
    stem_thickness_t_m : float
        Thickness of the vertical concrete stem (m).  Must be > 0.
    base_width_B_m : float
        Total base width B = toe_length + stem_thickness + heel_length (m).
        If provided it overrides toe_length + stem_thickness + heel_length
        (which must be consistent: B = toe + t + heel within 0.1 mm).
    base_thickness_h_m : float
        Thickness of the horizontal concrete base slab h (m).  Must be > 0
        and < H.
    heel_length_m : float
        Length of the heel (soil side) of the base, measured from the back
        face of the stem (m).  Must be ≥ 0.
    toe_length_m : float
        Length of the toe (front) of the base, measured from the front face
        of the stem (m).  Must be ≥ 0.
    concrete_unit_weight_kN_m3 : float
        Unit weight of concrete γ_c (kN/m³).  Default 24.0 kN/m³.
    """
    wall_height_H_m: float
    stem_thickness_t_m: float
    base_width_B_m: float
    base_thickness_h_m: float
    heel_length_m: float
    toe_length_m: float
    concrete_unit_weight_kN_m3: float = 24.0


@dataclass
class SoilSpec:
    """
    Backfill and founding soil properties.

    Parameters
    ----------
    unit_weight_kN_m3 : float
        Moist unit weight of backfill γ_s (kN/m³).  Must be > 0.
    friction_angle_phi_deg : float
        Effective friction angle of backfill φ (degrees).  Range (0, 50].
        Rankine Ka = tan²(45 - φ/2).
    base_friction_delta_deg : float
        Friction angle at base of footing–soil interface δ (degrees).
        Typically 0.5φ to 0.67φ for concrete on soil.  Must be ≥ 0 and ≤ φ.
    allowable_bearing_q_a_kPa : float
        Allowable bearing capacity of the founding soil q_a (kPa).
        Must be > 0.  The check confirms q_max ≤ q_a.
    """
    unit_weight_kN_m3: float
    friction_angle_phi_deg: float
    base_friction_delta_deg: float
    allowable_bearing_q_a_kPa: float


@dataclass
class RetainingWallReport:
    """
    Output of cantilever retaining wall stability check.

    Parameters
    ----------
    Ka : float
        Rankine active pressure coefficient Ka = tan²(45 - φ/2).
    Pa_kN_per_m : float
        Horizontal active resultant Pa = 0.5·γ_s·H²·Ka (kN/m).
    FoS_overturning : float
        Factor of safety against overturning about the toe.
        Adequate when ≥ 2.0 (Bowles §12-8).
    FoS_sliding : float
        Factor of safety against sliding along the base.
        Adequate when ≥ 1.5 (Bowles §12-9).
    q_max_kPa : float
        Maximum bearing pressure at the toe (trapezoidal distribution,
        kPa).
    FoS_bearing : float
        Factor of safety against bearing failure = q_a / q_max.
        Adequate when ≥ 3.0 (Bowles §12-10; typical geotechnical practice).
    all_adequate : bool
        True when all three FoS values are adequate.
    governing_failure_mode : str
        The failure mode with the lowest FoS ('overturning', 'sliding',
        or 'bearing'), or 'none' if all adequate.
    honest_caveat : str
        Scope limitations and applicable references.
    """
    Ka: float
    Pa_kN_per_m: float
    FoS_overturning: float
    FoS_sliding: float
    q_max_kPa: float
    FoS_bearing: float
    all_adequate: bool
    governing_failure_mode: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Adequacy thresholds (Bowles 5e §12)
# ---------------------------------------------------------------------------

_FOS_OVERTURNING_MIN = 2.0   # Bowles §12-8
_FOS_SLIDING_MIN = 1.5       # Bowles §12-9
_FOS_BEARING_MIN = 3.0       # Bowles §12-10


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def check_retaining_wall(
    wall: RetainingWallSpec,
    soil: SoilSpec,
) -> RetainingWallReport:
    """
    Check overturning, sliding, and bearing stability of a cantilevered
    concrete retaining wall under Rankine active earth pressure.

    Algorithm (Bowles 5e §12.3 / Das §13):
      1. Ka = tan²(45 - φ/2)
      2. Pa = 0.5 · γ_s · H² · Ka  (horizontal, at H/3)
      3. Weight components:
           W_stem = γ_c · t · (H - h)
           W_base = γ_c · B · h
           W_soil = γ_s · l_heel · (H - h)
         ΣW = W_stem + W_base + W_soil
      4. Moments about toe (stabilising positive):
           M_stem = W_stem · (l_toe + t/2)
           M_base = W_base · (B/2)
           M_soil = W_soil · (B - l_heel/2)
         ΣM_resist = M_stem + M_base + M_soil
         ΣM_overt  = Pa · (H/3)
      5. FoS_overturning = ΣM_resist / ΣM_overt
      6. FoS_sliding     = (ΣW · tan δ) / Pa
      7. Net moment about toe: ΣM_net = ΣM_resist - ΣM_overt
         Location of ΣW: x_bar = ΣM_net / ΣW  from toe
         Eccentricity:    e = B/2 - x_bar
         q_max = (ΣW / B) · (1 + 6e/B)
         FoS_bearing = q_a / q_max

    Parameters
    ----------
    wall : RetainingWallSpec
    soil : SoilSpec

    Returns
    -------
    RetainingWallReport

    Raises
    ------
    ValueError
        On invalid geometry or soil parameters.
    """
    # ---- Input validation -----------------------------------------------
    H = wall.wall_height_H_m
    t = wall.stem_thickness_t_m
    B = wall.base_width_B_m
    h = wall.base_thickness_h_m
    l_heel = wall.heel_length_m
    l_toe = wall.toe_length_m
    gam_c = wall.concrete_unit_weight_kN_m3

    if H <= 0:
        raise ValueError(f"wall_height_H_m must be > 0, got {H}")
    if t <= 0:
        raise ValueError(f"stem_thickness_t_m must be > 0, got {t}")
    if h <= 0:
        raise ValueError(f"base_thickness_h_m must be > 0, got {h}")
    if h >= H:
        raise ValueError(
            f"base_thickness_h_m ({h}) must be < wall_height_H_m ({H})"
        )
    if l_heel < 0:
        raise ValueError(f"heel_length_m must be >= 0, got {l_heel}")
    if l_toe < 0:
        raise ValueError(f"toe_length_m must be >= 0, got {l_toe}")
    if B <= 0:
        raise ValueError(f"base_width_B_m must be > 0, got {B}")
    if gam_c <= 0:
        raise ValueError(f"concrete_unit_weight_kN_m3 must be > 0, got {gam_c}")

    # Check geometric consistency: B ≈ toe + t + heel within 1 mm
    B_implied = l_toe + t + l_heel
    if abs(B_implied - B) > 0.001:
        raise ValueError(
            f"base_width_B_m ({B:.4f}) must equal "
            f"toe_length_m + stem_thickness_t_m + heel_length_m "
            f"({l_toe:.4f} + {t:.4f} + {l_heel:.4f} = {B_implied:.4f})"
        )

    gam_s = soil.unit_weight_kN_m3
    phi_deg = soil.friction_angle_phi_deg
    delta_deg = soil.base_friction_delta_deg
    q_a = soil.allowable_bearing_q_a_kPa

    if gam_s <= 0:
        raise ValueError(f"unit_weight_kN_m3 must be > 0, got {gam_s}")
    if phi_deg <= 0 or phi_deg > 50:
        raise ValueError(
            f"friction_angle_phi_deg must be in (0, 50], got {phi_deg}"
        )
    if delta_deg < 0 or delta_deg > phi_deg:
        raise ValueError(
            f"base_friction_delta_deg ({delta_deg}) must be in [0, phi={phi_deg}]"
        )
    if q_a <= 0:
        raise ValueError(f"allowable_bearing_q_a_kPa must be > 0, got {q_a}")

    # ---- Step 1: Rankine Ka -----------------------------------------------
    Ka = math.tan(math.radians(45.0 - phi_deg / 2.0)) ** 2

    # ---- Step 2: Active resultant Pa (horizontal) -------------------------
    # Pa = 0.5 · γ_s · H² · Ka  (kN/m)
    Pa = 0.5 * gam_s * H**2 * Ka

    # ---- Step 3: Weight components ----------------------------------------
    H_stem = H - h   # height of stem above base
    W_stem = gam_c * t * H_stem          # concrete stem (kN/m)
    W_base = gam_c * B * h              # concrete base slab (kN/m)
    W_soil = gam_s * l_heel * H_stem    # backfill on heel (kN/m)
    W_total = W_stem + W_base + W_soil

    # ---- Step 4: Moments about toe (stabilising) --------------------------
    # Distances from toe to centroid of each component:
    #   stem centroid is at x = l_toe + t/2
    #   base centroid is at x = B/2
    #   soil centroid is at x = B - l_heel/2  (heel soil measured from back)
    x_stem = l_toe + t / 2.0
    x_base = B / 2.0
    x_soil = B - l_heel / 2.0  # = l_toe + t + l_heel/2

    M_stem = W_stem * x_stem
    M_base = W_base * x_base
    M_soil = W_soil * x_soil
    M_resist = M_stem + M_base + M_soil

    # Overturning moment about toe: Pa acts at H/3 above base
    M_overt = Pa * (H / 3.0)

    # ---- Step 5: FoS overturning ------------------------------------------
    if M_overt <= 0:
        raise ValueError("Overturning moment is zero or negative — check inputs.")
    FoS_overturning = M_resist / M_overt

    # ---- Step 6: FoS sliding ----------------------------------------------
    delta_rad = math.radians(delta_deg)
    F_resist_slide = W_total * math.tan(delta_rad)   # sliding resistance (kN/m)
    # Pa is the horizontal driving force; no passive resistance counted
    FoS_sliding = F_resist_slide / Pa if Pa > 0 else float("inf")

    # ---- Step 7: Bearing pressure and FoS ---------------------------------
    # Location of resultant W from toe
    M_net = M_resist - M_overt
    if W_total <= 0:
        raise ValueError("Total vertical weight is zero or negative — check inputs.")
    x_bar = M_net / W_total           # distance from toe to resultant

    # Eccentricity from base centre
    e = B / 2.0 - x_bar

    # If e < 0: resultant falls outside the base on the heel side — tension zone
    # Standard practice: allow e up to B/6 for full-compression (kern); report q_max
    # using trapezoidal formula (valid for e ≤ B/6; conservative q_max otherwise)
    q_max = (W_total / B) * (1.0 + 6.0 * e / B)
    q_min = (W_total / B) * (1.0 - 6.0 * e / B)

    # If eccentricity exceeds B/6 the trapezoidal formula gives tension; use
    # triangular distribution:  q_max = 2·W / (3·x_bar)
    if e > B / 6.0:
        q_max = 2.0 * W_total / (3.0 * x_bar) if x_bar > 0 else float("inf")

    FoS_bearing = q_a / q_max if q_max > 0 else float("inf")

    # ---- Adequacy and governing failure mode ------------------------------
    ok_overt = FoS_overturning >= _FOS_OVERTURNING_MIN
    ok_slide = FoS_sliding >= _FOS_SLIDING_MIN
    ok_bear  = FoS_bearing >= _FOS_BEARING_MIN
    all_adequate = ok_overt and ok_slide and ok_bear

    # Governing = lowest normalised margin
    margins = {
        "overturning": FoS_overturning / _FOS_OVERTURNING_MIN,
        "sliding":     FoS_sliding / _FOS_SLIDING_MIN,
        "bearing":     FoS_bearing / _FOS_BEARING_MIN,
    }
    governing = min(margins, key=lambda k: margins[k])
    governing_failure_mode = "none" if all_adequate else governing

    # ---- Honest caveat ----------------------------------------------------
    caveat = (
        "Cantilevered concrete retaining wall stability — Rankine active earth pressure. "
        "Refs: Bowles 'Foundation Engineering' 5e §12.3; Das 'Principles of Geotechnical Engineering' §13. "
        f"Ka = {Ka:.4f}; Pa = {Pa:.2f} kN/m (at H/3 = {H/3:.3f} m). "
        f"FoS_overturning = {FoS_overturning:.2f} (min 2.0); "
        f"FoS_sliding = {FoS_sliding:.2f} (min 1.5); "
        f"FoS_bearing = {FoS_bearing:.2f} (min 3.0, q_max = {q_max:.1f} kPa). "
        "SCOPE LIMITATIONS: "
        "(1) Rankine ACTIVE pressure only — applicable to level backfill, cohesionless soil (c=0). "
        "Coulomb active pressure (wall friction δ, sloped backfill) NOT implemented. "
        "(2) NO surcharge load — add q·Ka·H to Pa separately if surcharge present. "
        "(3) NO seismic component — Mononobe-Okabe pseudo-static method (AASHTO LRFD §11.6.5, "
        "Das §13.12) NOT implemented; seismic zones require separate analysis. "
        "(4) NO passive resistance from soil in front of toe — conservative (safe-side) assumption. "
        "Passive resistance Pp = 0.5·γ·h_toe²·Kp can be added if toe is reliably embedded. "
        "(5) NO hydrostatic pressure — assumes free-draining backfill with weep holes / filter drain. "
        "(6) Bearing: trapezoidal pressure distribution (valid e ≤ B/6); "
        "triangular distribution used automatically when e > B/6. "
        "Allowable q_a must come from a geotechnical investigation; do not rely on assumed values. "
        "(7) Sliding friction coefficient = tan(δ) at base; no key / shear lug considered. "
        "Always verify design with a licensed geotechnical / structural engineer."
    )

    return RetainingWallReport(
        Ka=Ka,
        Pa_kN_per_m=Pa,
        FoS_overturning=FoS_overturning,
        FoS_sliding=FoS_sliding,
        q_max_kPa=q_max,
        FoS_bearing=FoS_bearing,
        all_adequate=all_adequate,
        governing_failure_mode=governing_failure_mode,
        honest_caveat=caveat,
    )
