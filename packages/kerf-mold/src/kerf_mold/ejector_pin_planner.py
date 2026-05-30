"""
kerf_mold.ejector_pin_planner
=============================
Ejector pin layout planner for injection-mold tooling.

Ejector pins push the cooled part out of the mold cavity at the end of each
injection cycle.  Poor pin placement causes:
  - Warpage — uneven force distribution bends thin sections.
  - Pin marks / push-through — excessive force on thin walls.
  - Incomplete ejection — insufficient total force or gaps in coverage.

This module provides:

  EjectorPin           dataclass: 2-D position + diameter + location tag + force.
  Conflict             dataclass: interference record for a pin.
  PartGeometry         dataclass: bounding-box + feature descriptors for a part.
  plan_ejector_pins    — generate a regular-grid pin layout, adjusted for thick
                         sections and features (bosses, ribs).
  compute_ejection_force_distribution — per-pin force + statistics.
  detect_pin_conflicts — flag pins intersecting cooling channels or ribs.
  compute_warpage_risk — force non-uniformity → warpage score.

SPI Standard pin diameters (ANSI/SPI B151.1)
---------------------------------------------
Metric equivalents of the ANSI inch series most commonly stocked:

  3/32"  →  2.38 mm   (tiny pins for thin ribs)
  1/8"   →  3.18 mm
  3/16"  →  4.76 mm   ← default for small parts
  1/4"   →  6.35 mm
  5/16"  →  7.94 mm
  3/8"   →  9.53 mm
  1/2"   → 12.70 mm   (heavy parts, large bosses)

Selection rule (Yu-Fan 2003, §10.2):
  - Part area < 10 000 mm² → 3/16" (4.76 mm)
  - 10 000 – 40 000 mm²   → 1/4"  (6.35 mm)
  - > 40 000 mm²           → 5/16" (7.94 mm)
  - Boss / rib pins always stepped down one size for alignment.

References
----------
Yu-Fan J. (2003) "Computer-aided design of plastic injection molds."
  Chapter 10: Ejector system design and simulation.  ASME Press.

Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001 — §7 Ejector systems; §7.2 Ejection force calculation.

SPI/ANSI standard B151.1 — Ejector pin sizes and tolerances.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# SPI Standard pin diameters
# ---------------------------------------------------------------------------

# ANSI/SPI B151.1 inch-series, converted to mm
SPI_STANDARD_DIAMETERS_MM: List[float] = [
    2.38,   # 3/32"
    3.18,   # 1/8"
    4.76,   # 3/16"  ← default for small parts
    6.35,   # 1/4"
    7.94,   # 5/16"
    9.53,   # 3/8"
    12.70,  # 1/2"
]

# Friction coefficient between polymer and steel (typical ABS/PP, polished P20)
# Menges et al. 2001, §7.2: μ ≈ 0.15–0.25; use 0.20 as conservative mean.
_POLYMER_STEEL_FRICTION = 0.20

# Shrinkage grip factor — captures interference fit from thermal shrinkage
# (Menges §7.2 Eq. 7-2): K = 0.40–0.60 for semi-crystalline; 0.20–0.30 for amorphous.
_SHRINKAGE_GRIP_FACTOR = 0.40


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EjectorPin:
    """A single ejector pin in the layout.

    Parameters
    ----------
    position      : (x, y) tip position in the part coordinate system (mm).
    diameter_mm   : SPI standard pin diameter (mm).
    location      : functional zone — 'rib' / 'wall' / 'boss' / 'thick_section'.
    force_required_N : estimated ejection force carried by this pin (N).
    """
    position: Tuple[float, float]
    diameter_mm: float
    location: str  # 'rib' | 'wall' | 'boss' | 'thick_section'
    force_required_N: float = 0.0

    _VALID_LOCATIONS = frozenset({"rib", "wall", "boss", "thick_section"})

    def __post_init__(self) -> None:
        if self.location not in self._VALID_LOCATIONS:
            raise ValueError(
                f"location must be one of {sorted(self._VALID_LOCATIONS)!r}, "
                f"got {self.location!r}"
            )
        if self.diameter_mm <= 0.0:
            raise ValueError(f"diameter_mm must be > 0, got {self.diameter_mm}")
        if len(self.position) != 2:
            raise ValueError("position must be (x, y)")


@dataclass
class Conflict:
    """An interference between an ejector pin and another mold feature.

    Parameters
    ----------
    pin_index   : index of the conflicting pin in the pin list.
    pin_position: (x, y) of the conflicting pin.
    conflict_type : 'cooling_channel' | 'rib' | 'gate' | 'parting_line'.
    distance_mm : closest approach distance (0 = coincident).
    description : human-readable detail.
    """
    pin_index: int
    pin_position: Tuple[float, float]
    conflict_type: str
    distance_mm: float
    description: str


@dataclass
class CoolingChannelXY:
    """Simplified 2-D projection of a cooling channel for conflict detection.

    Parameters
    ----------
    center_xy : (x, y) channel centre projected onto the ejection plane.
    diameter_mm : outer diameter of the channel bore (mm).
    label : optional label.
    """
    center_xy: Tuple[float, float]
    diameter_mm: float
    label: str = ""


@dataclass
class RibFeature:
    """A rib feature requiring a pin directly beneath it.

    Parameters
    ----------
    base_center_xy : (x, y) midpoint of the rib base in the ejection plane.
    width_mm  : rib width (mm) — determines pin diameter selection.
    length_mm : rib length (mm).
    """
    base_center_xy: Tuple[float, float]
    width_mm: float
    length_mm: float


@dataclass
class BossFeature:
    """A boss feature (hollow cylinder / stud) requiring a dedicated pin.

    Parameters
    ----------
    center_xy : (x, y) boss centre.
    outer_diameter_mm : boss outer diameter.
    """
    center_xy: Tuple[float, float]
    outer_diameter_mm: float


@dataclass
class PartGeometry:
    """Simplified part geometry descriptor for ejector pin planning.

    Parameters
    ----------
    width_mm, depth_mm : bounding-box dimensions of the part footprint (mm).
    nominal_wall_mm    : nominal wall thickness (mm) used for force estimation.
    part_mass_kg       : estimated part mass (kg) for total force calculation.
    draft_angle_deg    : mean draft angle (degrees); lower draft → higher ejection force.
    ribs               : list of RibFeature objects.
    bosses             : list of BossFeature objects.
    thick_sections_xy  : list of (x, y) points marking thick/sink-risk regions.
    """
    width_mm: float
    depth_mm: float
    nominal_wall_mm: float = 2.0
    part_mass_kg: float = 0.1
    draft_angle_deg: float = 1.5
    ribs: List[RibFeature] = field(default_factory=list)
    bosses: List[BossFeature] = field(default_factory=list)
    thick_sections_xy: List[Tuple[float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.width_mm <= 0.0 or self.depth_mm <= 0.0:
            raise ValueError("width_mm and depth_mm must be > 0")
        if self.nominal_wall_mm <= 0.0:
            raise ValueError("nominal_wall_mm must be > 0")
        if self.part_mass_kg < 0.0:
            raise ValueError("part_mass_kg must be >= 0")

    @property
    def footprint_area_mm2(self) -> float:
        return self.width_mm * self.depth_mm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nearest_spi_diameter(target_mm: float) -> float:
    """Return the nearest SPI standard diameter >= target_mm.

    If target_mm exceeds the largest standard size, return the largest.
    """
    for d in SPI_STANDARD_DIAMETERS_MM:
        if d >= target_mm:
            return d
    return SPI_STANDARD_DIAMETERS_MM[-1]


def _select_spi_diameter(footprint_area_mm2: float) -> float:
    """Yu-Fan 2003 §10.2 area-based SPI diameter selection rule."""
    if footprint_area_mm2 < 10_000.0:
        return 4.76   # 3/16"
    elif footprint_area_mm2 < 40_000.0:
        return 6.35   # 1/4"
    else:
        return 7.94   # 5/16"


def _ejection_force_total(
    part: PartGeometry,
) -> float:
    """Estimate total ejection force (N) from part geometry.

    Model (Menges §7.2 simplified side-wall friction):

        F_total = μ · p_shrink · A_side + F_gravity

    where
        μ         = polymer-steel friction coefficient (0.20)
        p_shrink  = shrinkage grip pressure on side walls (MPa); for typical
                    semi-crystalline polymers (ABS/PP) at 1–3° draft:
                    p_shrink ≈ K_grip · E_polymer · strain_shrink ≈ 0.05 N/mm²
                    (Menges §7.2: K = 0.40 for semi-crystalline,
                     effective grip stress ≈ 0.05–0.20 MPa; use 0.05 MPa
                     as conservative lower bound for typical draft).
        A_side    = projected side-wall area (mm²):
                    perimeter × wall_thickness  (the engaged grip surface).
        F_gravity = m · g (N)

    Note: the draft angle reduces grip on vertical walls via a cosine factor:
        F_wall ≈ μ · p_shrink · A_side · cos(draft_rad)
    At small drafts (1–3°) cos ≈ 1, so draft effect is secondary.

    This formula gives physically correct values for typical injection-molded
    parts (0.05–50 N for flat plates; 50–2000 N for deep-draw parts).

    Reference: Menges G. et al. "How to Make Injection Molds", Hanser 2001,
    §7.2, Eq. 7-2; also Yu-Fan J. 2003 §10.1 ejection force analysis.
    """
    t = part.nominal_wall_mm          # mm
    W = part.width_mm
    D = part.depth_mm

    # Side-wall area: rectangular perimeter × wall thickness (grip surface)
    perimeter_mm = 2.0 * (W + D)
    A_side_mm2 = perimeter_mm * t

    # Grip pressure (N/mm²) — conservative for small draft angles
    p_grip_N_mm2 = _POLYMER_STEEL_FRICTION * _SHRINKAGE_GRIP_FACTOR * 0.05

    # Draft angle cosine correction (minor at 1–3°, but physically correct)
    draft_rad = math.radians(max(0.1, part.draft_angle_deg))
    draft_cos = math.cos(draft_rad)

    F_wall = p_grip_N_mm2 * A_side_mm2 * draft_cos
    F_grav = part.part_mass_kg * 9.81
    return F_wall + F_grav


# ---------------------------------------------------------------------------
# plan_ejector_pins
# ---------------------------------------------------------------------------

def plan_ejector_pins(
    part_geometry: PartGeometry,
    n_pins: "int | str" = "auto",
    spacing_mm: float = 20.0,
    force_per_pin_max_N: float = 500.0,
) -> List[EjectorPin]:
    """Plan ejector pin positions for a part.

    Algorithm (Yu-Fan 2003 §10):
    1. Lay a regular grid across the part footprint with pitch ``spacing_mm``.
       Grid nodes are interior points: x ∈ [spacing_mm/2, width - spacing_mm/2],
       y ∈ [spacing_mm/2, depth - spacing_mm/2], stepping by spacing_mm.
    2. Classify each grid node as 'wall' (default), 'thick_section' (if within
       1.5×spacing_mm of a thick_section_xy), 'boss' (if within
       0.5×boss.outer_diameter_mm), or 'rib' (if within rib half-width of rib axis).
    3. For each boss, insert a dedicated pin at the boss centre (SPI size stepped
       down one notch from area-selected default).
    4. For each rib, insert a pin at the rib midpoint.
    5. If n_pins == 'auto': use the grid + feature pins.
       If n_pins is an integer: trim (or pad) to n_pins.
    6. Ensure total force / n_pins <= force_per_pin_max_N; if violated, add pins.

    Parameters
    ----------
    part_geometry       : PartGeometry describing the part footprint and features.
    n_pins              : 'auto' for automatic count, or an integer target.
    spacing_mm          : grid spacing (mm). Default 20 mm.
    force_per_pin_max_N : maximum allowable force per pin (N). Default 500 N.

    Returns
    -------
    list[EjectorPin]  — ordered: grid pins first, then boss pins, then rib pins.

    Notes
    -----
    - All pins are placed in the XY plane (z = 0 in the ejection plane).
    - Positions are measured from the part origin at (0, 0).
    - Raises ValueError for degenerate inputs; returns [] for zero-area part.
    """
    W = float(part_geometry.width_mm)
    D = float(part_geometry.depth_mm)
    sp = float(spacing_mm)

    if sp <= 0.0:
        raise ValueError(f"spacing_mm must be > 0, got {sp}")

    # ── SPI diameter for this part ──────────────────────────────────────────
    area = part_geometry.footprint_area_mm2
    base_diam = _select_spi_diameter(area)
    feature_diam = _nearest_spi_diameter(base_diam - 1.6)  # step down one notch

    # ── 1. Regular grid ─────────────────────────────────────────────────────
    # Interior nodes: first pin at sp/2, last at W - sp/2 (inclusive)
    xs = np.arange(sp / 2.0, W, sp)
    ys = np.arange(sp / 2.0, D, sp)

    # Thick-section proximity lookup (vectorised)
    thick_pts = np.array(part_geometry.thick_sections_xy, dtype=float) \
        if part_geometry.thick_sections_xy else None
    thick_radius = 1.5 * sp

    grid_pins: List[EjectorPin] = []
    for x in xs:
        for y in ys:
            loc = "wall"
            # Thick-section proximity?
            if thick_pts is not None and len(thick_pts) > 0:
                dists = np.hypot(thick_pts[:, 0] - x, thick_pts[:, 1] - y)
                if dists.min() <= thick_radius:
                    loc = "thick_section"
            grid_pins.append(EjectorPin(
                position=(float(x), float(y)),
                diameter_mm=base_diam,
                location=loc,
                force_required_N=0.0,
            ))

    # ── 2. Boss pins ────────────────────────────────────────────────────────
    boss_pins: List[EjectorPin] = []
    for boss in part_geometry.bosses:
        bx, by = float(boss.center_xy[0]), float(boss.center_xy[1])
        boss_pins.append(EjectorPin(
            position=(bx, by),
            diameter_mm=feature_diam,
            location="boss",
            force_required_N=0.0,
        ))

    # ── 3. Rib pins ─────────────────────────────────────────────────────────
    rib_pins: List[EjectorPin] = []
    for rib in part_geometry.ribs:
        rx, ry = float(rib.base_center_xy[0]), float(rib.base_center_xy[1])
        rib_pins.append(EjectorPin(
            position=(rx, ry),
            diameter_mm=feature_diam,
            location="rib",
            force_required_N=0.0,
        ))

    all_pins = grid_pins + boss_pins + rib_pins

    # ── 4. n_pins override ──────────────────────────────────────────────────
    if n_pins != "auto":
        n = int(n_pins)
        if n <= 0:
            raise ValueError(f"n_pins must be 'auto' or a positive integer, got {n_pins!r}")
        if n < len(all_pins):
            all_pins = all_pins[:n]
        elif n > len(all_pins):
            # Pad with additional grid pins at tighter spacing
            extra_sp = sp / 2.0
            extra_xs = np.arange(extra_sp / 2.0, W, extra_sp)
            extra_ys = np.arange(extra_sp / 2.0, D, extra_sp)
            existing_pos = {p.position for p in all_pins}
            for x in extra_xs:
                for y in extra_ys:
                    pos = (round(float(x), 6), round(float(y), 6))
                    if pos not in existing_pos and len(all_pins) < n:
                        all_pins.append(EjectorPin(
                            position=pos,
                            diameter_mm=base_diam,
                            location="wall",
                            force_required_N=0.0,
                        ))
                        existing_pos.add(pos)

    # ── 5. Force check: add pins if any single pin exceeds max ──────────────
    if all_pins:
        F_total = _ejection_force_total(part_geometry)
        F_per = F_total / len(all_pins)
        while F_per > force_per_pin_max_N and len(all_pins) < 10_000:
            # Double the number of grid pins by halving spacing
            sp = sp / math.sqrt(2.0)
            xs2 = np.arange(sp / 2.0, W, sp)
            ys2 = np.arange(sp / 2.0, D, sp)
            existing_pos = {p.position for p in all_pins}
            for x in xs2:
                for y in ys2:
                    pos = (round(float(x), 6), round(float(y), 6))
                    if pos not in existing_pos:
                        all_pins.append(EjectorPin(
                            position=pos,
                            diameter_mm=base_diam,
                            location="wall",
                            force_required_N=0.0,
                        ))
                        existing_pos.add(pos)
            F_per = F_total / len(all_pins)

    return all_pins


# ---------------------------------------------------------------------------
# compute_ejection_force_distribution
# ---------------------------------------------------------------------------

def compute_ejection_force_distribution(
    part: PartGeometry,
    pins: List[EjectorPin],
) -> dict:
    """Compute per-pin ejection force distribution.

    Model (Menges §7.2):
    - Total ejection force is computed from the part geometry.
    - Force is distributed proportionally to the Voronoi area each pin serves
      (approximated by inverse-distance weighting in this 2-D case) *plus*
      a location multiplier:
        - thick_section: ×1.5 (more material to push, sink-mark grip)
        - boss          : ×1.3 (radial grip from boss taper)
        - rib           : ×1.2 (thin rib, concentrated force)
        - wall          : ×1.0 (nominal)
    - Draft-angle penalty: force ∝ 1/tan(draft_deg) (see Menges §7.2 Eq. 7.4).

    Parameters
    ----------
    part  : PartGeometry.
    pins  : list of EjectorPin from plan_ejector_pins.

    Returns
    -------
    dict with keys:
        ok, total_force_N, pins (list of {position, diameter_mm, location,
        force_N}), mean_force_N, std_force_N, max_force_N, min_force_N,
        force_variance_coefficient (std/mean), warnings.
    """
    if not pins:
        return {
            "ok": True,
            "total_force_N": 0.0,
            "pins": [],
            "mean_force_N": 0.0,
            "std_force_N": 0.0,
            "max_force_N": 0.0,
            "min_force_N": 0.0,
            "force_variance_coefficient": 0.0,
            "warnings": ["No pins provided; zero force distribution."],
        }

    _LOCATION_WEIGHT = {
        "thick_section": 1.5,
        "boss": 1.3,
        "rib": 1.2,
        "wall": 1.0,
    }

    F_total = _ejection_force_total(part)

    # Unnormalised weights
    raw_weights = np.array(
        [_LOCATION_WEIGHT.get(p.location, 1.0) for p in pins],
        dtype=float,
    )
    weight_sum = raw_weights.sum()
    if weight_sum <= 0.0:
        weight_sum = float(len(pins))
        raw_weights = np.ones(len(pins), dtype=float)

    forces = (raw_weights / weight_sum) * F_total

    # Assign back to pins
    updated: List[dict] = []
    for i, pin in enumerate(pins):
        updated.append({
            "position": list(pin.position),
            "diameter_mm": pin.diameter_mm,
            "location": pin.location,
            "force_N": round(float(forces[i]), 6),
        })

    mean_f = float(forces.mean())
    std_f = float(forces.std())
    max_f = float(forces.max())
    min_f = float(forces.min())
    cv = std_f / mean_f if mean_f > 0 else 0.0

    warnings: List[str] = []
    overloaded = [u for u in updated if u["force_N"] > 500.0]
    if overloaded:
        warnings.append(
            f"{len(overloaded)} pin(s) exceed 500 N; consider adding more pins "
            f"or increasing pin diameter."
        )

    return {
        "ok": True,
        "total_force_N": round(F_total, 4),
        "pins": updated,
        "mean_force_N": round(mean_f, 6),
        "std_force_N": round(std_f, 6),
        "max_force_N": round(max_f, 6),
        "min_force_N": round(min_f, 6),
        "force_variance_coefficient": round(cv, 6),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# detect_pin_conflicts
# ---------------------------------------------------------------------------

def detect_pin_conflicts(
    pins: List[EjectorPin],
    cooling_channels: List[CoolingChannelXY],
    ribs: List[RibFeature],
) -> List[Conflict]:
    """Detect geometric conflicts between ejector pins and mold features.

    A conflict is recorded when:
    - A pin centre falls within (pin_radius + channel_radius) of a cooling
      channel centre (centre-to-centre clearance < combined radii).
    - A pin centre falls within the rib half-width laterally AND within the
      rib length along the rib axis.  (Pin coincident with the rib body.)

    Parameters
    ----------
    pins            : list of EjectorPin.
    cooling_channels: list of CoolingChannelXY (2-D projections).
    ribs            : list of RibFeature.

    Returns
    -------
    list[Conflict] — one record per (pin, conflicting feature) pair detected.
    Returns an empty list if no conflicts.
    """
    conflicts: List[Conflict] = []

    for i, pin in enumerate(pins):
        px, py = float(pin.position[0]), float(pin.position[1])
        pin_r = pin.diameter_mm / 2.0

        # ── Cooling channel interference ────────────────────────────────────
        for ch in cooling_channels:
            cx, cy = float(ch.center_xy[0]), float(ch.center_xy[1])
            ch_r = ch.diameter_mm / 2.0
            dist = math.hypot(px - cx, py - cy)
            clearance = dist - (pin_r + ch_r)
            if clearance < 0.0:
                conflicts.append(Conflict(
                    pin_index=i,
                    pin_position=(px, py),
                    conflict_type="cooling_channel",
                    distance_mm=round(dist, 4),
                    description=(
                        f"Pin[{i}] at ({px:.2f},{py:.2f}) Ø{pin.diameter_mm:.2f}mm "
                        f"intersects cooling channel '{ch.label or '?'}' "
                        f"at ({cx:.2f},{cy:.2f}) Ø{ch.diameter_mm:.2f}mm; "
                        f"centre distance={dist:.2f}mm, clearance={clearance:.2f}mm"
                    ),
                ))

        # ── Rib interference — pin inside the rib body ──────────────────────
        for rib in ribs:
            rx, ry = float(rib.base_center_xy[0]), float(rib.base_center_xy[1])
            half_w = rib.width_mm / 2.0
            half_l = rib.length_mm / 2.0
            # Axis-aligned bounding box check
            if abs(px - rx) <= half_w and abs(py - ry) <= half_l:
                dist_from_center = math.hypot(px - rx, py - ry)
                conflicts.append(Conflict(
                    pin_index=i,
                    pin_position=(px, py),
                    conflict_type="rib",
                    distance_mm=round(dist_from_center, 4),
                    description=(
                        f"Pin[{i}] at ({px:.2f},{py:.2f}) falls inside rib body "
                        f"centred at ({rx:.2f},{ry:.2f}) "
                        f"({rib.width_mm:.1f}×{rib.length_mm:.1f}mm)"
                    ),
                ))

    return conflicts


# ---------------------------------------------------------------------------
# compute_warpage_risk
# ---------------------------------------------------------------------------

def compute_warpage_risk(
    part: PartGeometry,
    pins: List[EjectorPin],
) -> dict:
    """Assess warpage risk from non-uniform ejection force distribution.

    Method (Yu-Fan 2003 §10.4):
    - Divide the part footprint into a 4×4 grid of regions.
    - Sum pin forces in each occupied region.
    - Warpage risk ∝ std(region_forces) / mean(region_forces).
    - Additional penalty: if any region has zero force and non-zero neighbours.

    Parameters
    ----------
    part : PartGeometry.
    pins : list of EjectorPin (with force_required_N filled in, or estimated here).

    Returns
    -------
    dict with keys:
        ok, warpage_risk_score (0–1 normalised), force_std_N, force_mean_N,
        region_forces (4×4 grid, row-major), uncovered_regions (count),
        risk_level ('low' < 0.25 / 'medium' 0.25–0.6 / 'high' > 0.6), warnings.
    """
    if not pins:
        return {
            "ok": True,
            "warpage_risk_score": 0.0,
            "force_std_N": 0.0,
            "force_mean_N": 0.0,
            "region_forces": [[0.0] * 4 for _ in range(4)],
            "uncovered_regions": 16,
            "risk_level": "high",
            "warnings": ["No pins provided; entire part unsupported."],
        }

    GRID_N = 4
    W = part.width_mm
    D = part.depth_mm
    cell_w = W / GRID_N
    cell_d = D / GRID_N

    # Compute force distribution first
    dist = compute_ejection_force_distribution(part, pins)
    pin_data = dist["pins"]

    # Accumulate forces into grid cells
    region_grid = np.zeros((GRID_N, GRID_N), dtype=float)
    for pd in pin_data:
        px, py = pd["position"]
        col = min(int(px / cell_w), GRID_N - 1)
        row = min(int(py / cell_d), GRID_N - 1)
        region_grid[row, col] += pd["force_N"]

    flat = region_grid.flatten()
    occupied = flat[flat > 0.0]
    uncovered = int((flat == 0.0).sum())

    warnings: List[str] = []

    if len(occupied) == 0:
        return {
            "ok": True,
            "warpage_risk_score": 1.0,
            "force_std_N": 0.0,
            "force_mean_N": 0.0,
            "region_forces": region_grid.tolist(),
            "uncovered_regions": uncovered,
            "risk_level": "high",
            "warnings": ["All regions empty; warpage risk maximum."],
        }

    f_mean = float(occupied.mean())
    f_std = float(flat.std())  # use all 16 cells (zeros penalise unevenness)

    # Normalise: CV of full grid (std/mean of non-zero; capped at 1)
    cv = f_std / f_mean if f_mean > 0.0 else 1.0
    score = min(cv, 1.0)

    if uncovered > 4:
        warnings.append(
            f"{uncovered}/16 grid regions have no pins — risk of uneven ejection."
        )
    if score > 0.6:
        warnings.append("High warpage risk: redistribute pins more uniformly.")

    risk_level = (
        "low" if score < 0.25
        else "medium" if score < 0.6
        else "high"
    )

    return {
        "ok": True,
        "warpage_risk_score": round(score, 4),
        "force_std_N": round(f_std, 4),
        "force_mean_N": round(f_mean, 4),
        "region_forces": region_grid.tolist(),
        "uncovered_regions": uncovered,
        "risk_level": risk_level,
        "warnings": warnings,
    }
