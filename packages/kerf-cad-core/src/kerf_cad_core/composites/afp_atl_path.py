"""
kerf_cad_core.composites.afp_atl_path — Automated Fiber Placement / Automated Tape Laying
robot path generator.

Generates parallel fiber paths over composite ply boundaries for AFP/ATL machines.
Paths are straight parallel courses at the ply orientation angle (no steered fibers).

HONEST limitations
------------------
- Straight parallel paths only — no variable-angle steered-fiber paths.
- Flat or gently-curved mold surfaces only — no geodesic path projection on
  highly curved geometry.
- Generates APT CL (Cutter Location) output per AIA NAS 9300 legacy format.

References
----------
Lopes, C.S., Camanho, P.P., Gürdal, Z. & Tatting, B.F. (2010).
    "Variable-stiffness composite panels: Effects of stiffness variation on the
    large-deflection and post-buckling behaviour." Composites Part A: Applied
    Science and Manufacturing, 41(6), 796–805.

Coriolis Composites AFP Programming Manual, Rev 3.2 (publicly available).

AIA NAS 9300 Series — Numerical Control Processor Output, Vol. III: APT Language.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CompositePlyDef:
    """Definition of a single composite ply for AFP/ATL path generation.

    Attributes
    ----------
    ply_id : str
        Unique identifier for this ply, e.g. 'PLY-001'.
    ply_orientation_deg : float
        Fiber/tape orientation in degrees relative to the reference axis.
        Typical values: 0, ±45, 90, ±60.
    material : str
        Material system designation, e.g. 'IM7/8552', 'AS4/3501-6', 'T300/5208'.
    thickness_mm : float
        Nominal cured ply thickness in millimetres (e.g. 0.125 mm for IM7/8552).
    boundary_3d : list of (x, y, z)
        Closed 3-D boundary polygon of the ply on the mold surface (metres).
        Last point need not repeat first point — closing is automatic.
    """
    ply_id: str
    ply_orientation_deg: float
    material: str
    thickness_mm: float
    boundary_3d: List[Tuple[float, float, float]]


@dataclass
class AfpAtlMachineSpec:
    """AFP/ATL machine specification.

    Attributes
    ----------
    name : str
        Machine designation, e.g. 'Coriolis C1', 'Electroimpact AFP', 'MAG Cincinnati'.
    tape_width_mm : float
        Tape/tow slit width in mm.  Common values: 6.35 mm (1/4 in), 12.7 mm (1/2 in),
        25.4 mm (1 in) for ATL.
    head_count : int
        Number of AFP heads (tows) placed simultaneously.  Typical: 8–32 for AFP,
        1 for ATL.
    max_lay_rate_m_per_min : float
        Maximum tape lay rate in metres per minute.
    """
    name: str
    tape_width_mm: float
    head_count: int
    max_lay_rate_m_per_min: float


@dataclass
class FiberPath:
    """A single AFP/ATL tape course (one pass of the head).

    Attributes
    ----------
    path_id : str
        Unique course identifier, e.g. 'PLY-001-COURSE-042'.
    centerline_3d : list of (x, y, z)
        3-D centreline of the tape course.  For flat plies this is two points
        (start, end); curved surfaces would have more.
    orientation_at_points : list of (dx, dy, dz)
        Unit tangent vector of the tape at each centreline sample point.
    cut_segments : list of (start_idx, end_idx)
        Index pairs into centerline_3d marking tape-add (start) and tape-cut
        (end) events for course trimming at the ply boundary.
    """
    path_id: str
    centerline_3d: List[Tuple[float, float, float]]
    orientation_at_points: List[Tuple[float, float, float]]
    cut_segments: List[Tuple[int, int]]


@dataclass
class AfpAtlProgram:
    """Complete AFP/ATL layup program for one ply.

    Attributes
    ----------
    paths : list of FiberPath
        All tape courses for the ply.
    total_length_m : float
        Sum of all course centreline lengths in metres.
    estimated_time_min : float
        Estimated lay time in minutes at machine max_lay_rate.
    head_count_used : int
        Number of heads engaged (≤ machine head_count).
    coverage_pct : float
        Fraction (0–100) of the ply area covered by tape.
    waste_pct : float
        Fraction (0–100) of total tape laid that falls outside ply boundary
        (trim waste).
    """
    paths: List[FiberPath]
    total_length_m: float
    estimated_time_min: float
    head_count_used: int
    coverage_pct: float
    waste_pct: float


# ---------------------------------------------------------------------------
# Geometry helpers (pure Python + math — no numpy required at call site)
# ---------------------------------------------------------------------------

def _ply_bounding_box_2d(
    boundary: List[Tuple[float, float, float]],
    theta_rad: float,
) -> Tuple[float, float, float, float]:
    """Project boundary onto rotated frame and return (u_min, u_max, v_min, v_max).

    The rotated frame has its u-axis along the tape direction (theta_rad from X)
    and its v-axis perpendicular (the cross-tape direction).
    """
    cos_t = math.cos(theta_rad)
    sin_t = math.sin(theta_rad)
    us = [x * cos_t + y * sin_t for (x, y, _) in boundary]
    vs = [-x * sin_t + y * cos_t for (x, y, _) in boundary]
    return min(us), max(us), min(vs), max(vs)


def _rotate_direction(theta_rad: float) -> Tuple[float, float, float]:
    """Unit tangent vector in the tape direction (XY plane)."""
    return (math.cos(theta_rad), math.sin(theta_rad), 0.0)


def _polygon_area_2d(pts: List[Tuple[float, float]]) -> float:
    """Shoelace formula for polygon area (absolute value)."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _segment_clip_to_band(
    u_start: float,
    u_end: float,
    v_centre: float,
    boundary: List[Tuple[float, float, float]],
    theta_rad: float,
) -> Tuple[float, float, bool]:
    """Clip a tape course centreline to the ply boundary using the Sutherland-Hodgman
    approach projected onto the tape-direction frame.

    Returns (clipped_u_start, clipped_u_end, intersects) in the rotated frame.
    This is a conservative line-polygon intersection along the tape direction.
    """
    cos_t = math.cos(theta_rad)
    sin_t = math.sin(theta_rad)

    # Project boundary to (u, v) rotated frame
    proj: List[Tuple[float, float]] = []
    for (x, y, _) in boundary:
        u = x * cos_t + y * sin_t
        v = -x * sin_t + y * cos_t
        proj.append((u, v))

    # Find the u extents of the polygon at v = v_centre (scan-line)
    # by iterating over polygon edges
    u_crossings: List[float] = []
    n = len(proj)
    for i in range(n):
        u0, v0 = proj[i]
        u1, v1 = proj[(i + 1) % n]
        # Does edge cross v = v_centre?
        if (v0 <= v_centre < v1) or (v1 <= v_centre < v0):
            if abs(v1 - v0) < 1e-12:
                continue
            t_cross = (v_centre - v0) / (v1 - v0)
            u_cross = u0 + t_cross * (u1 - u0)
            u_crossings.append(u_cross)

    if len(u_crossings) < 2:
        return u_start, u_end, False

    u_crossings.sort()
    # Use outermost crossings for simple convex / near-convex boundaries
    clip_min = u_crossings[0]
    clip_max = u_crossings[-1]
    effective_start = max(u_start, clip_min)
    effective_end = min(u_end, clip_max)
    if effective_end <= effective_start:
        return u_start, u_end, False
    return effective_start, effective_end, True


# ---------------------------------------------------------------------------
# Core path-generation function
# ---------------------------------------------------------------------------

def generate_afp_paths(
    ply: CompositePlyDef,
    machine: AfpAtlMachineSpec,
) -> AfpAtlProgram:
    """Generate parallel fiber/tape paths over *ply* at the ply orientation angle.

    Algorithm
    ---------
    1. Project the ply boundary into a rotated 2-D frame whose u-axis is parallel
       to the tape direction (ply.ply_orientation_deg) and v-axis is perpendicular.
    2. Step across the ply in the v (cross-tape) direction at intervals equal to
       the effective tape width (machine.tape_width_mm converted to metres × head_count).
    3. For each course v-position, clip the tape centreline to the ply boundary
       using a scan-line intersection.
    4. Assemble FiberPath records; compute coverage and waste statistics.

    HONEST: straight parallel paths only — no steered-fiber variable-angle paths.
    See Lopes et al. (2010) for variable-stiffness AFP theory.

    Parameters
    ----------
    ply : CompositePlyDef
        Ply definition including 3-D boundary on the mold surface.
    machine : AfpAtlMachineSpec
        Machine parameters (tape width, head count, lay rate).

    Returns
    -------
    AfpAtlProgram
        Complete layup program for the ply.

    References
    ----------
    Lopes, C.S. et al. (2010). Composites Part A, 41(6), 796–805.
    Coriolis Composites AFP Programming Manual, Rev 3.2.
    """
    if not ply.boundary_3d or len(ply.boundary_3d) < 3:
        raise ValueError("ply.boundary_3d must have at least 3 points")
    if machine.tape_width_mm <= 0:
        raise ValueError("machine.tape_width_mm must be > 0")
    if machine.head_count < 1:
        raise ValueError("machine.head_count must be >= 1")

    theta_rad = math.radians(ply.ply_orientation_deg)
    tape_width_m = machine.tape_width_mm / 1000.0
    # Each pass of the machine lays head_count tapes side-by-side
    course_pitch_m = tape_width_m * machine.head_count

    # Bounding box in rotated frame
    u_min_bb, u_max_bb, v_min_bb, v_max_bb = _ply_bounding_box_2d(
        ply.boundary_3d, theta_rad
    )

    # 2-D boundary for area computation (drop Z)
    boundary_2d = [(x, y) for (x, y, _) in ply.boundary_3d]
    ply_area = _polygon_area_2d(boundary_2d)

    tan_dir = _rotate_direction(theta_rad)
    # Perpendicular direction (cross-tape)
    perp_dir = (-math.sin(theta_rad), math.cos(theta_rad), 0.0)

    cos_t = math.cos(theta_rad)
    sin_t = math.sin(theta_rad)

    paths: List[FiberPath] = []
    total_length_m = 0.0
    total_tape_clipped_m = 0.0  # tape actually covering ply
    total_tape_laid_m = 0.0     # full course length before trimming

    # Centre each strip band on v positions from v_min to v_max
    # First strip centre at v_min + tape_width/2 (or aligned flush)
    # We start at v_min_bb so first tape edge is at the boundary
    v_start = v_min_bb + tape_width_m / 2.0
    v_pos = v_start
    course_index = 0

    while v_pos <= v_max_bb + tape_width_m / 2.0:
        # Full course runs from u_min_bb to u_max_bb in the tape direction
        clip_start, clip_end, intersects = _segment_clip_to_band(
            u_min_bb, u_max_bb, v_pos, ply.boundary_3d, theta_rad
        )
        if intersects and clip_end > clip_start:
            # Convert clipped u,v back to 3D XY
            def rotated_to_3d(u: float, v: float) -> Tuple[float, float, float]:
                x = u * cos_t - v * sin_t
                y = u * sin_t + v * cos_t
                return (x, y, 0.0)

            pt_start_3d = rotated_to_3d(clip_start, v_pos)
            pt_end_3d = rotated_to_3d(clip_end, v_pos)
            full_start_3d = rotated_to_3d(u_min_bb, v_pos)
            full_end_3d = rotated_to_3d(u_max_bb, v_pos)

            # Clipped (within-ply) length
            clipped_length = clip_end - clip_start
            full_length = u_max_bb - u_min_bb

            path = FiberPath(
                path_id=f"{ply.ply_id}-COURSE-{course_index:04d}",
                centerline_3d=[pt_start_3d, pt_end_3d],
                orientation_at_points=[tan_dir, tan_dir],
                cut_segments=[(0, 1)],
            )
            paths.append(path)
            total_length_m += clipped_length
            total_tape_clipped_m += clipped_length
            total_tape_laid_m += full_length

        v_pos += course_pitch_m
        course_index += 1

    # Coverage: tape area vs ply area
    tape_area_covered = total_tape_clipped_m * tape_width_m * machine.head_count
    coverage_pct = min(100.0, (tape_area_covered / ply_area * 100.0) if ply_area > 0 else 0.0)

    # Waste: tape laid outside ply / total laid
    waste_total = total_tape_laid_m - total_tape_clipped_m
    waste_pct = (waste_total / total_tape_laid_m * 100.0) if total_tape_laid_m > 0 else 0.0

    # Time estimate at machine max lay rate
    estimated_time_min = (
        total_length_m / machine.max_lay_rate_m_per_min
        if machine.max_lay_rate_m_per_min > 0 else 0.0
    )

    return AfpAtlProgram(
        paths=paths,
        total_length_m=total_length_m,
        estimated_time_min=estimated_time_min,
        head_count_used=min(machine.head_count, 1) if paths else 0,
        coverage_pct=coverage_pct,
        waste_pct=max(0.0, waste_pct),
    )


# ---------------------------------------------------------------------------
# APT CL file export
# ---------------------------------------------------------------------------

def export_apt_cl_file(program: AfpAtlProgram) -> str:
    """Serialize *program* to an APT (Automatically Programmed Tools) CL file.

    APT CL (Cutter Location) is the legacy NC format for composite AFP/ATL machines.
    Each tape course is represented as a GOTO statement moving between start and end
    points with FEDRAT (feed rate) and SPINDL (head enable) directives.

    Format follows AIA NAS 9300 Vol. III APT Language specification.

    Parameters
    ----------
    program : AfpAtlProgram
        The AFP/ATL layup program to serialize.

    Returns
    -------
    str
        APT CL file content as a string.

    References
    ----------
    AIA NAS 9300 Series — Numerical Control Processor Output,
    Vol. III: APT Language (public specification).
    Coriolis Composites AFP Programming Manual, Rev 3.2.
    """
    lines: List[str] = []
    lines.append("PARTNO  KERF AFP PROGRAM")
    lines.append("MACHIN  AFP,1")
    lines.append(f"UNITS   MM")
    lines.append(f"$$ Total courses: {len(program.paths)}")
    lines.append(f"$$ Total length: {program.total_length_m:.4f} M")
    lines.append(f"$$ Coverage: {program.coverage_pct:.1f} PCT")
    lines.append(f"$$ Waste:    {program.waste_pct:.1f} PCT")
    lines.append("")

    for path in program.paths:
        lines.append(f"$$ Course: {path.path_id}")
        lines.append(f"FEDRAT  MMPM,{1000.0:.1f}")
        lines.append("SPINDL  ON")

        if path.centerline_3d:
            # Rapid to start position
            sx, sy, sz = path.centerline_3d[0]
            lines.append(f"RAPID")
            lines.append(f"GOTO    / {sx * 1000.0:.6f},{sy * 1000.0:.6f},{sz * 1000.0:.6f}")
            lines.append("SPINDL  HEAD,ON")

            # Lay tape to each subsequent point
            for pt in path.centerline_3d[1:]:
                px, py, pz = pt
                lines.append(
                    f"GOTO    / {px * 1000.0:.6f},{py * 1000.0:.6f},{pz * 1000.0:.6f}"
                )

        lines.append("SPINDL  OFF")
        lines.append("")

    lines.append("FINI")
    return "\n".join(lines)
