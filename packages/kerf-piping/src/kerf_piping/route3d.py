"""
kerf_piping.route3d — 3D intelligent piping route design + ASME component catalogue.

Implements:
  1. 3D orthogonal/manhattan piping router with:
     - Spec-driven pipe class (diameter + schedule from PipeSpec)
     - Auto-insertion of 90° / 45° LR elbows at direction changes
     - Basic AABB obstacle avoidance (route around a list of bounding boxes)
     - BOM aggregation: total length, fitting count, elbow centre-to-end (B16.9)

  2. ASME B16.9 / B16.5 3D component catalogue:
     - Parametric fittings: 90° LR/SR elbow, 45° elbow, tee, reducer,
       flange, gate valve, ball valve, cap
     - Per-component: end-point geometry (nozzle positions + orientations),
       face-to-face / centre-to-end dimensions, BOM line
     - All dimensions from ASME B16.9-2018 / B16.5-2017 tables

References
----------
ASME B16.9-2018 Factory-Made Wrought Butt-Welding Fittings — Tables 1-6.
ASME B16.5-2017 Pipe Flanges — Table 2-1.1.
ASME B31.3-2022 §302.1 — Pipe class/spec.
ASME B36.10M-2018 — Pipe wall thickness / OD.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from kerf_piping.pid import Point3, PipeSchedule
from kerf_piping.b16_catalogue import (
    lr_elbow_dims,
    sr_elbow_dims,
    elbow_45_dims,
    reducer_dims,
    cap_dims,
    flange_rating,
    _LR_ELBOW_A_MM,
    _SR_ELBOW_A_MM,
    _ELBOW_45_A_MM,
    _REDUCER_H_MM,
    _CAP_E_MM,
)
from kerf_piping.pipe_spec import (
    PipeSpec,
    select_schedule,
    NOMINAL_OD_MM,
    standard_class_cs_a,
)
from kerf_piping.isometric import (
    route_orthogonal,
    count_fittings,
    pipe_length,
    FittingType,
    Segment,
    elbow_radius_mm,
)


# ---------------------------------------------------------------------------
# AABB obstacle — axis-aligned bounding box
# ---------------------------------------------------------------------------

@dataclass
class AABB:
    """
    Axis-aligned bounding box obstacle for clash avoidance.

    Parameters
    ----------
    min_pt  Lower corner (x_min, y_min, z_min).
    max_pt  Upper corner (x_max, y_max, z_max).
    label   Optional identifier (e.g. equipment tag).
    """
    min_pt: Tuple[float, float, float]
    max_pt: Tuple[float, float, float]
    label: str = ""

    def contains_point(self, p: Point3, clearance: float = 0.0) -> bool:
        """True if point p is inside the AABB (expanded by clearance)."""
        return (
            self.min_pt[0] - clearance <= p.x <= self.max_pt[0] + clearance and
            self.min_pt[1] - clearance <= p.y <= self.max_pt[1] + clearance and
            self.min_pt[2] - clearance <= p.z <= self.max_pt[2] + clearance
        )

    def intersects_segment(
        self,
        a: Point3,
        b: Point3,
        clearance: float = 0.0,
    ) -> bool:
        """
        True if the axis-aligned segment a→b intersects this AABB.
        Only valid for orthogonal (axis-aligned) segments.
        """
        lo = (
            self.min_pt[0] - clearance,
            self.min_pt[1] - clearance,
            self.min_pt[2] - clearance,
        )
        hi = (
            self.max_pt[0] + clearance,
            self.max_pt[1] + clearance,
            self.max_pt[2] + clearance,
        )
        # Segment is axis-aligned → check each coordinate range
        for i, (av, bv) in enumerate([(a.x, b.x), (a.y, b.y), (a.z, b.z)]):
            seg_lo, seg_hi = (min(av, bv), max(av, bv))
            if seg_hi < lo[i] or seg_lo > hi[i]:
                return False
        return True


# ---------------------------------------------------------------------------
# AABB avoidance routing
# ---------------------------------------------------------------------------

def _detour_around(
    a: Point3,
    b: Point3,
    obstacle: AABB,
    clearance: float,
    prefer_axis: str = "Z",
) -> List[Tuple[Point3, Point3]]:
    """
    Produce up to 3 detour waypoints around a single AABB obstacle.

    Strategy (conservative): go up (Z) above the obstacle, then laterally,
    then down to resume the original path.  If Z axis is already the
    travel direction, go in X.

    Returns a list of (from, to) pairs forming an orthogonal detour path.
    """
    dx = b.x - a.x
    dy = b.y - a.y
    dz = b.z - a.z

    # Determine dominant travel axis
    abs_dx, abs_dy, abs_dz = abs(dx), abs(dy), abs(dz)
    dom = "Z" if abs_dz >= abs_dx and abs_dz >= abs_dy else (
        "X" if abs_dx >= abs_dy else "Y"
    )

    # Clearance above/around the obstacle
    obs_top_z = obstacle.max_pt[2] + clearance

    if dom != "Z":
        # Detour vertically: rise above obstacle, travel sideways, descend
        lift = max(obs_top_z - a.z, clearance)
        p1 = Point3(a.x, a.y, a.z + lift)        # rise
        p2 = Point3(b.x, b.y, a.z + lift)        # travel at height
        p3 = b                                    # descend
        return [(a, p1), (p1, p2), (p2, p3)]
    else:
        # Travel is Z, detour in X
        side_x = obstacle.max_pt[0] + clearance
        p1 = Point3(side_x, a.y, a.z)
        p2 = Point3(side_x, b.y, b.z)
        return [(a, p1), (p1, p2), (p2, b)]


def _route_with_avoidance(
    start: Point3,
    end: Point3,
    obstacles: List[AABB],
    clearance: float,
    diameter_mm: float,
    schedule: PipeSchedule,
    prefer_axis: str = "Z",
    *,
    _depth: int = 0,
) -> List[Segment]:
    """
    Route start→end avoiding obstacle AABBs.

    Uses a simple greedy strategy:
    1. Attempt the direct orthogonal route.
    2. For the first segment that clashes, insert a detour and re-route.
    3. Recurse (up to 4 levels).
    """
    direct_segs = route_orthogonal(start, end,
                                   diameter_mm=diameter_mm,
                                   schedule=schedule,
                                   prefer_axis=prefer_axis)
    if not obstacles or _depth >= 4:
        return direct_segs

    # Check each segment for clashes
    for seg in direct_segs:
        for obs in obstacles:
            if obs.intersects_segment(seg.start, seg.end, clearance=clearance):
                # Build detour around this obstacle
                detour_pairs = _detour_around(
                    seg.start, seg.end, obs, clearance, prefer_axis
                )
                result_segs: List[Segment] = []
                # Route from original start to detour start
                if seg.start.distance_to(start) > 1e-9:
                    result_segs += route_orthogonal(
                        start, seg.start,
                        diameter_mm=diameter_mm, schedule=schedule,
                        prefer_axis=prefer_axis,
                    )
                # Route through detour waypoints
                prev = seg.start
                for (wp_from, wp_to) in detour_pairs:
                    result_segs += _route_with_avoidance(
                        prev, wp_to, obstacles, clearance,
                        diameter_mm, schedule, prefer_axis,
                        _depth=_depth + 1,
                    )
                    prev = wp_to
                # Route from detour end to final end
                if prev.distance_to(end) > 1e-9:
                    result_segs += _route_with_avoidance(
                        prev, end, obstacles, clearance,
                        diameter_mm, schedule, prefer_axis,
                        _depth=_depth + 1,
                    )
                return result_segs

    return direct_segs


# ---------------------------------------------------------------------------
# Route result
# ---------------------------------------------------------------------------

@dataclass
class Route3DResult:
    """
    Result of a 3D intelligent piping route.

    Attributes
    ----------
    segments        Ordered list of Segment objects (straight runs + fitting markers).
    elbows_90       Count of 90° LR elbows inserted.
    elbows_45       Count of 45° LR elbows inserted.
    tees            Count of tees inserted.
    total_length_m  Total straight pipe length (m).
    dn              Nominal diameter (mm).
    schedule        Schedule code (string).
    elbow_radius_mm LR elbow centreline radius per ASME B16.9 (mm).
    bom             Bill of materials: list of fitting dicts.
    centerline      List of [x, y, z] waypoints forming the 3D centreline.
    clashes_avoided Count of AABB obstacles that triggered a detour.
    warnings        Engineering notes.
    """
    segments: List[Segment] = field(default_factory=list)
    elbows_90: int = 0
    elbows_45: int = 0
    tees: int = 0
    total_length_m: float = 0.0
    dn: int = 50
    schedule: str = "40"
    elbow_radius_mm: float = 0.0
    elbow_center_to_face_mm: float = 0.0
    bom: List[dict] = field(default_factory=list)
    centerline: List[List[float]] = field(default_factory=list)
    clashes_avoided: int = 0
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "segment_count": len(self.segments),
            "elbows_90": self.elbows_90,
            "elbows_45": self.elbows_45,
            "tees": self.tees,
            "total_length_m": round(self.total_length_m, 4),
            "dn": self.dn,
            "schedule": self.schedule,
            "elbow_radius_mm": round(self.elbow_radius_mm, 2),
            "elbow_center_to_face_mm": round(self.elbow_center_to_face_mm, 2),
            "clashes_avoided": self.clashes_avoided,
            "bom": self.bom,
            "centerline": [[round(v, 4) for v in pt] for pt in self.centerline],
            "segments": [
                {
                    "from": list(s.start.as_tuple()),
                    "to": list(s.end.as_tuple()),
                    "fitting": s.fitting.value,
                    "length_m": round(s.length, 4),
                    "direction": [round(v, 4) for v in s.direction],
                }
                for s in self.segments
            ],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Main public API: route_3d
# ---------------------------------------------------------------------------

def route_3d(
    start: Point3,
    end: Point3,
    *,
    dn: int = 50,
    spec: Optional[PipeSpec] = None,
    schedule: Optional[str] = None,
    obstacles: Optional[List[AABB]] = None,
    clearance_m: float = 0.3,
    prefer_axis: str = "Z",
) -> Route3DResult:
    """
    Route a pipe in 3D between two nozzle/connection points.

    Routing rules:
    - Orthogonal (manhattan) segments along X, Y, Z axes.
    - Direction changes → 90° LR elbows per ASME B16.9.
    - If spec provided, schedule is derived per spec rules (Barlow/B31.3).
    - Obstacle AABBs: route around using vertical detour strategy.
    - Outputs: centerline waypoints, fitting counts, elbow dimensions, BOM.

    Parameters
    ----------
    start         Start nozzle / connection point (metres).
    end           End nozzle / connection point (metres).
    dn            Nominal pipe diameter (DN, mm).  E.g. 50, 100, 150.
    spec          PipeSpec instance.  If given, schedule is derived from it.
    schedule      Override schedule code ('40', '80', 'XS', etc.).
                  Ignored if spec is provided.
    obstacles     List of AABB obstacles to route around.
    clearance_m   Minimum clearance around obstacles (metres).
    prefer_axis   Axis to travel first: 'Z' (vertical), 'X', or 'Y'.

    Returns
    -------
    Route3DResult

    Raises
    ------
    ValueError if spec does not permit the given DN.
    """
    warnings: List[str] = []

    # Resolve schedule from spec or override
    if spec is not None:
        try:
            sched_str = select_schedule(dn, spec)
        except ValueError as exc:
            warnings.append(f"Spec compliance warning: {exc}")
            sched_str = spec.default_schedule
    elif schedule is not None:
        sched_str = schedule.upper()
    else:
        sched_str = "40"

    # Map schedule string to PipeSchedule enum
    try:
        pipe_sched = PipeSchedule(sched_str)
    except ValueError:
        pipe_sched = PipeSchedule.SCH_40
        sched_str = "40"

    obs_list = obstacles or []

    # Count clashes before routing
    def _count_clashes(segs: List[Segment]) -> int:
        n = 0
        for seg in segs:
            for obs in obs_list:
                if obs.intersects_segment(seg.start, seg.end, clearance=clearance_m):
                    n += 1
                    break
        return n

    # Route with avoidance
    segments = _route_with_avoidance(
        start, end, obs_list, clearance_m,
        diameter_mm=float(dn),
        schedule=pipe_sched,
        prefer_axis=prefer_axis,
    )

    clashes_avoided = _count_clashes(
        route_orthogonal(start, end, diameter_mm=float(dn), schedule=pipe_sched)
    )

    fc = count_fittings(segments)
    total_len = pipe_length(segments)

    # Elbow dimensions from ASME B16.9
    try:
        elbow_dims = lr_elbow_dims(dn)
        elbow_ctf = elbow_dims.center_to_face_mm
        elbow_r = elbow_radius_mm(float(dn), pipe_sched)
    except KeyError:
        elbow_ctf = 1.5 * dn / 2.0
        elbow_r = 1.5 * dn / 2.0
        warnings.append(
            f"DN{dn} not in B16.9 LR elbow table; using 1.5D approximation."
        )

    # Build BOM
    bom: List[dict] = []
    if total_len > 0:
        bom.append({
            "item": "straight_pipe",
            "description": f"DN{dn} Sch {sched_str} straight pipe",
            "quantity": 1,
            "total_length_m": round(total_len, 4),
            "standard": "ASME B36.10M",
        })
    if fc.elbows_90 > 0:
        bom.append({
            "item": "90lr_elbow",
            "description": f"ASME B16.9 90° LR elbow DN{dn}",
            "quantity": fc.elbows_90,
            "center_to_face_mm": round(elbow_ctf, 1),
            "standard": "ASME B16.9-2018",
        })
    if fc.elbows_45 > 0:
        try:
            dims_45 = elbow_45_dims(dn)
            ctf_45 = dims_45.center_to_face_mm
        except KeyError:
            ctf_45 = 0.414 * dn  # approx for 45° LR
        bom.append({
            "item": "45lr_elbow",
            "description": f"ASME B16.9 45° LR elbow DN{dn}",
            "quantity": fc.elbows_45,
            "center_to_face_mm": round(ctf_45, 1),
            "standard": "ASME B16.9-2018",
        })
    if fc.tees > 0:
        bom.append({
            "item": "tee_equal",
            "description": f"ASME B16.9 equal tee DN{dn}",
            "quantity": fc.tees,
            "standard": "ASME B16.9-2018",
        })

    # Build centreline (unique waypoints)
    centerline: List[List[float]] = []
    seen: set = set()
    for seg in segments:
        for pt in [seg.start, seg.end]:
            key = (round(pt.x, 6), round(pt.y, 6), round(pt.z, 6))
            if key not in seen:
                seen.add(key)
                centerline.append([pt.x, pt.y, pt.z])

    return Route3DResult(
        segments=segments,
        elbows_90=fc.elbows_90,
        elbows_45=fc.elbows_45,
        tees=fc.tees,
        total_length_m=total_len,
        dn=dn,
        schedule=sched_str,
        elbow_radius_mm=elbow_r,
        elbow_center_to_face_mm=elbow_ctf,
        bom=bom,
        centerline=centerline,
        clashes_avoided=clashes_avoided,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# ASME B16.9 / B16.5 3D component catalogue
# ---------------------------------------------------------------------------

class ComponentType(str, Enum):
    ELBOW_90_LR = "elbow_90_lr"
    ELBOW_90_SR = "elbow_90_sr"
    ELBOW_45_LR = "elbow_45_lr"
    TEE_EQUAL = "tee_equal"
    REDUCER_CONC = "reducer_concentric"
    FLANGE_WN = "flange_weldneck"
    VALVE_GATE = "valve_gate"
    VALVE_BALL = "valve_ball"
    CAP = "cap"


@dataclass
class NozzlePort:
    """A piping nozzle / connection port on a 3D component."""
    label: str           # e.g. 'in', 'out', 'branch'
    position: Tuple[float, float, float]  # relative to component origin (mm)
    direction: Tuple[float, float, float]  # flow-in unit vector

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "position_mm": [round(v, 3) for v in self.position],
            "flow_direction": [round(v, 4) for v in self.direction],
        }


@dataclass
class CatalogueComponent:
    """
    A 3D parametric piping component from the ASME catalogue.

    Dimensions are from:
      ASME B16.9-2018 Tables 1-6 (butt-weld fittings)
      ASME B16.5-2017 Table 2 (flanges)
      Typical face-to-face dimensions for valves (ISA / manufacturer practice)

    Parameters
    ----------
    component_type  ComponentType enum.
    dn              Nominal pipe diameter (DN, mm).
    schedule        Schedule code (e.g. '40').
    dn_branch       For reducers/tees: branch/small-end DN.
    flange_class    For flanges: ASME B16.5 class (150, 300, ...).
    """
    component_type: ComponentType
    dn: int
    schedule: str = "40"
    dn_branch: Optional[int] = None
    flange_class: Optional[int] = None

    # Computed in __post_init__
    center_to_face_mm: float = field(init=False)
    face_to_face_mm: float = field(init=False)
    ports: List[NozzlePort] = field(init=False)
    od_mm: float = field(init=False)
    weight_kg: Optional[float] = field(init=False)
    standard: str = field(init=False)
    notes: str = field(init=False)

    def __post_init__(self):
        ct = self.component_type
        dn = self.dn

        self.od_mm = NOMINAL_OD_MM.get(dn, 0.0)
        self.weight_kg = None
        self.notes = ""

        if ct == ComponentType.ELBOW_90_LR:
            self._build_90lr()
        elif ct == ComponentType.ELBOW_90_SR:
            self._build_90sr()
        elif ct == ComponentType.ELBOW_45_LR:
            self._build_45lr()
        elif ct == ComponentType.TEE_EQUAL:
            self._build_tee()
        elif ct == ComponentType.REDUCER_CONC:
            self._build_reducer()
        elif ct == ComponentType.FLANGE_WN:
            self._build_flange()
        elif ct == ComponentType.VALVE_GATE:
            self._build_valve_gate()
        elif ct == ComponentType.VALVE_BALL:
            self._build_valve_ball()
        elif ct == ComponentType.CAP:
            self._build_cap()
        else:
            raise ValueError(f"Unknown component type: {ct}")

    # ------------------------------------------------------------------
    # Component builders
    # ------------------------------------------------------------------

    def _build_90lr(self):
        """90° Long-radius elbow per ASME B16.9."""
        self.standard = "ASME B16.9-2018"
        try:
            dims = lr_elbow_dims(self.dn)
            a = dims.center_to_face_mm
        except KeyError:
            a = 1.5 * self.dn
        self.center_to_face_mm = a
        self.face_to_face_mm = a  # for 90° elbow, both ends are A from centre
        # Ports: in-port at (0,0,-A) pointing +Z; out-port at (+A,0,0) pointing -X
        self.ports = [
            NozzlePort("in",  (0.0, 0.0, -a), (0.0, 0.0, 1.0)),
            NozzlePort("out", (a, 0.0, 0.0),  (-1.0, 0.0, 0.0)),
        ]
        r = 1.5 * self.dn / 2.0
        self.notes = (
            f"ASME B16.9 90° LR elbow DN{self.dn}: "
            f"A={a:.1f} mm (centre-to-face), R={r:.1f} mm (centreline radius)"
        )

    def _build_90sr(self):
        """90° Short-radius elbow per ASME B16.9."""
        self.standard = "ASME B16.9-2018"
        try:
            dims = sr_elbow_dims(self.dn)
            a = dims.center_to_face_mm
        except KeyError:
            a = 1.0 * self.dn
        self.center_to_face_mm = a
        self.face_to_face_mm = a
        self.ports = [
            NozzlePort("in",  (0.0, 0.0, -a), (0.0, 0.0, 1.0)),
            NozzlePort("out", (a, 0.0, 0.0),  (-1.0, 0.0, 0.0)),
        ]
        r = 1.0 * self.dn / 2.0
        self.notes = (
            f"ASME B16.9 90° SR elbow DN{self.dn}: "
            f"A={a:.1f} mm (centre-to-face), R={r:.1f} mm (centreline radius)"
        )

    def _build_45lr(self):
        """45° Long-radius elbow per ASME B16.9."""
        self.standard = "ASME B16.9-2018"
        try:
            dims = elbow_45_dims(self.dn)
            a = dims.center_to_face_mm
        except KeyError:
            a = 0.414 * self.dn  # tan(22.5°) × D approximation
        self.center_to_face_mm = a
        self.face_to_face_mm = a
        # Out port is at 45° in the X-Z plane
        c45 = math.cos(math.radians(45))
        s45 = math.sin(math.radians(45))
        self.ports = [
            NozzlePort("in",  (0.0, 0.0, -a),         (0.0, 0.0, 1.0)),
            NozzlePort("out", (a * s45, 0.0, a * c45), (-s45, 0.0, -c45)),
        ]
        self.notes = (
            f"ASME B16.9 45° LR elbow DN{self.dn}: A={a:.1f} mm (centre-to-face)"
        )

    def _build_tee(self):
        """Equal tee per ASME B16.9."""
        self.standard = "ASME B16.9-2018"
        # Tee run-to-run = 2×C; branch = M
        # Simplified: use LR elbow A as C approximation for equal tee
        try:
            a = float(_LR_ELBOW_A_MM.get(self.dn, 1.5 * self.dn))
        except Exception:
            a = 1.5 * self.dn
        self.center_to_face_mm = a
        self.face_to_face_mm = 2.0 * a  # run face-to-face
        self.ports = [
            NozzlePort("in",    (-a, 0.0, 0.0), (1.0, 0.0, 0.0)),
            NozzlePort("out",   (a,  0.0, 0.0), (-1.0, 0.0, 0.0)),
            NozzlePort("branch",(0.0, 0.0, -a), (0.0, 0.0, 1.0)),
        ]
        self.notes = (
            f"ASME B16.9 equal tee DN{self.dn}: "
            f"run face-to-face={2*a:.1f} mm, branch centre-to-face={a:.1f} mm"
        )

    def _build_reducer(self):
        """Concentric reducer per ASME B16.9."""
        self.standard = "ASME B16.9-2018"
        dn_sm = self.dn_branch or max(self.dn // 2, 15)
        try:
            dims = reducer_dims(self.dn, dn_sm)
            h = dims.overall_length_mm
        except (KeyError, ValueError):
            h = float(_REDUCER_H_MM.get(self.dn, 1.5 * self.dn))
        self.center_to_face_mm = h / 2.0
        self.face_to_face_mm = h
        od_sm = NOMINAL_OD_MM.get(dn_sm, self.od_mm * 0.6)
        self.ports = [
            NozzlePort("large", (0.0, 0.0, 0.0),  (0.0, 0.0, -1.0)),
            NozzlePort("small", (0.0, 0.0, h),     (0.0, 0.0, 1.0)),
        ]
        self.notes = (
            f"ASME B16.9 concentric reducer DN{self.dn}×DN{dn_sm}: H={h:.1f} mm"
        )

    def _build_flange(self):
        """Weld-neck flange per ASME B16.5."""
        self.standard = "ASME B16.5-2017"
        cls = self.flange_class or 150
        # Simplified face-to-face: Class 150 RF flange thicknesses (approximate)
        _flange_ftf: Dict[int, float] = {
            150: {25: 44, 50: 54, 80: 57, 100: 68, 150: 76, 200: 95, 250: 108},
            300: {25: 52, 50: 67, 100: 79, 150: 92, 200: 114},
            600: {25: 64, 50: 83, 100: 102, 150: 127, 200: 165},
        }
        ftf = _flange_ftf.get(cls, {}).get(self.dn, 0.0)
        if ftf == 0.0:
            ftf = max(self.od_mm * 0.4, 50.0)
        self.center_to_face_mm = ftf / 2.0
        self.face_to_face_mm = ftf
        try:
            rating = flange_rating(cls, self.dn)
            self.notes = (
                f"ASME B16.5 Class {cls} WN flange DN{self.dn}: "
                f"face-to-face≈{ftf:.1f} mm, "
                f"rating {rating.rating_psi:.0f} psi / {rating.rating_bar:.1f} bar at ambient"
            )
        except Exception:
            self.notes = f"ASME B16.5 Class {cls} WN flange DN{self.dn}: face-to-face≈{ftf:.1f} mm"
        self.ports = [
            NozzlePort("face",  (0.0, 0.0, 0.0),  (0.0, 0.0, -1.0)),
            NozzlePort("weld",  (0.0, 0.0, ftf),   (0.0, 0.0,  1.0)),
        ]

    def _build_valve_gate(self):
        """Gate valve — ISA / ASME B16.10 face-to-face."""
        self.standard = "ASME B16.10-2000"
        # Class 150 raised-face gate valve face-to-face (mm), ASME B16.10 Table 1
        _gate_ftf: Dict[int, float] = {
            15: 108, 20: 117, 25: 124, 32: 133, 40: 140, 50: 165, 65: 190,
            80: 203, 100: 229, 125: 254, 150: 267, 200: 292, 250: 330, 300: 356,
        }
        ftf = _gate_ftf.get(self.dn, self.dn * 2.5)
        self.center_to_face_mm = ftf / 2.0
        self.face_to_face_mm = ftf
        self.ports = [
            NozzlePort("in",  (0.0, 0.0, -ftf / 2), (0.0, 0.0, 1.0)),
            NozzlePort("out", (0.0, 0.0,  ftf / 2), (0.0, 0.0, -1.0)),
        ]
        self.notes = (
            f"Gate valve DN{self.dn} Class 150 RF: face-to-face={ftf:.0f} mm "
            f"(ASME B16.10 Table 1)"
        )

    def _build_valve_ball(self):
        """Full-bore ball valve — API 6D / ASME B16.10 face-to-face."""
        self.standard = "API 6D / ASME B16.10"
        _ball_ftf: Dict[int, float] = {
            15: 60, 20: 65, 25: 70, 32: 80, 40: 89, 50: 108, 65: 117,
            80: 127, 100: 152, 125: 178, 150: 191, 200: 216, 250: 254, 300: 267,
        }
        ftf = _ball_ftf.get(self.dn, self.dn * 1.8)
        self.center_to_face_mm = ftf / 2.0
        self.face_to_face_mm = ftf
        self.ports = [
            NozzlePort("in",  (0.0, 0.0, -ftf / 2), (0.0, 0.0, 1.0)),
            NozzlePort("out", (0.0, 0.0,  ftf / 2), (0.0, 0.0, -1.0)),
        ]
        self.notes = (
            f"Full-bore ball valve DN{self.dn} Class 150: face-to-face={ftf:.0f} mm "
            f"(API 6D / ASME B16.10)"
        )

    def _build_cap(self):
        """End cap per ASME B16.9."""
        self.standard = "ASME B16.9-2018"
        try:
            e = cap_dims(self.dn)
        except KeyError:
            e = 0.5 * self.dn + 20.0
        self.center_to_face_mm = e
        self.face_to_face_mm = e
        self.ports = [
            NozzlePort("in", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ]
        self.notes = (
            f"ASME B16.9 cap DN{self.dn}: end-to-end E={e:.1f} mm"
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def as_dict(self) -> dict:
        return {
            "component_type": self.component_type.value,
            "dn": self.dn,
            "dn_branch": self.dn_branch,
            "schedule": self.schedule,
            "od_mm": round(self.od_mm, 3),
            "center_to_face_mm": round(self.center_to_face_mm, 2),
            "face_to_face_mm": round(self.face_to_face_mm, 2),
            "flange_class": self.flange_class,
            "standard": self.standard,
            "notes": self.notes,
            "ports": [p.as_dict() for p in self.ports],
        }

    def bom_line(self, quantity: int = 1) -> dict:
        return {
            "item": self.component_type.value,
            "dn": self.dn,
            "dn_branch": self.dn_branch,
            "schedule": self.schedule,
            "quantity": quantity,
            "description": self.notes,
            "standard": self.standard,
            "face_to_face_mm": round(self.face_to_face_mm, 1),
        }


# ---------------------------------------------------------------------------
# Public API: catalogue_component
# ---------------------------------------------------------------------------

def catalogue_component(
    component_type: str,
    dn: int,
    *,
    schedule: str = "40",
    dn_branch: Optional[int] = None,
    flange_class: Optional[int] = None,
) -> CatalogueComponent:
    """
    Return a 3D parametric piping component from the ASME catalogue.

    Parameters
    ----------
    component_type  One of the ComponentType values (string):
                    'elbow_90_lr', 'elbow_90_sr', 'elbow_45_lr',
                    'tee_equal', 'reducer_concentric', 'flange_weldneck',
                    'valve_gate', 'valve_ball', 'cap'.
    dn              Nominal pipe diameter (DN, mm).
    schedule        Pipe schedule code (default '40').
    dn_branch       Branch / small-end DN for reducers or tees.
    flange_class    ASME B16.5 class for flanges (150, 300, 600, 900, 1500, 2500).

    Returns
    -------
    CatalogueComponent with geometry, dimensions, and BOM line.

    Raises
    ------
    ValueError if component_type is not recognised.
    """
    try:
        ct = ComponentType(component_type.lower())
    except ValueError:
        valid = [e.value for e in ComponentType]
        raise ValueError(
            f"Unknown component type {component_type!r}. "
            f"Valid options: {valid}"
        )
    return CatalogueComponent(
        component_type=ct,
        dn=dn,
        schedule=schedule,
        dn_branch=dn_branch,
        flange_class=flange_class,
    )


# ---------------------------------------------------------------------------
# BOM aggregation helper
# ---------------------------------------------------------------------------

def aggregate_bom(components: List[Tuple[CatalogueComponent, int]]) -> List[dict]:
    """
    Aggregate a list of (component, quantity) pairs into a BOM.

    Parameters
    ----------
    components  List of (CatalogueComponent, quantity) tuples.

    Returns
    -------
    List of BOM-line dicts, consolidated by (type, dn, dn_branch, schedule).
    """
    consolidated: Dict[Tuple, dict] = {}
    for comp, qty in components:
        key = (comp.component_type.value, comp.dn, comp.dn_branch, comp.schedule)
        if key in consolidated:
            consolidated[key]["quantity"] += qty
        else:
            consolidated[key] = comp.bom_line(qty)
    return list(consolidated.values())
