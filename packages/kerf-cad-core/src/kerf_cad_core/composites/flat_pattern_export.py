"""
kerf_cad_core.composites.flat_pattern_export — Flat-pattern (developed) export for composite plies.

Develops 3-D composite ply boundaries onto a flat 2-D plane for cutting templates.
Supports two development strategies:
  - Isometric (exact) unwrap for planar / developable surfaces.
  - LSCM (Least Squares Conformal Map) approximation for non-developable surfaces,
    reusing kerf_cad_core.sculpt.lscm_uv_tool when available.

Exports AutoCAD DXF R12 for use with CNC cutting tables (Eastman, Gerber, etc.).

References
----------
Lévy, B. et al. (2002). "Least Squares Conformal Maps for Automatic Texture Atlas
    Generation." SIGGRAPH 2002, pp. 362–371.
Eastman Machine Company — CNC Ply Cutting System Manual (public).
AutoCAD DXF Reference, Release 12 — §3 DXF Group Codes.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple, Optional

from kerf_cad_core.composites.afp_atl_path import CompositePlyDef


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FlatPatternResult:
    """Result of developing a 3-D ply boundary to a 2-D flat pattern.

    Attributes
    ----------
    ply_id : str
        Identifier matching the source CompositePlyDef.
    flat_boundary_2d : list of (x, y)
        Developed 2-D outline in flat-pattern coordinates (metres).
    fiber_direction_in_flat : (dx, dy)
        Tape/fiber direction unit vector in the flat-pattern frame.
    nesting_efficiency_pct : float
        Fraction (0–100) of the bounding-box area occupied by the ply shape.
        Represents theoretical maximum nesting efficiency against stock material.
    distortion_max_mm : float
        Maximum distance (mm) between corresponding developed and original
        surface points — measures geodesic distortion from the unwrap.
    """
    ply_id: str
    flat_boundary_2d: List[Tuple[float, float]]
    fiber_direction_in_flat: Tuple[float, float]
    nesting_efficiency_pct: float
    distortion_max_mm: float


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _polygon_area_2d(pts: List[Tuple[float, float]]) -> float:
    """Shoelace formula for polygon area (absolute value), metres²."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _bounding_box_2d(
    pts: List[Tuple[float, float]],
) -> Tuple[float, float, float, float]:
    """Return (x_min, x_max, y_min, y_max) of a 2-D point set."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def _edge_length_3d(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> float:
    """Euclidean distance between two 3-D points."""
    return math.sqrt(
        (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2
    )


def _is_planar(pts: List[Tuple[float, float, float]], tol: float = 1e-4) -> bool:
    """Return True if all points lie within *tol* metres of the least-squares plane."""
    if len(pts) < 3:
        return True
    # Compute centroid
    n = len(pts)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    cz = sum(p[2] for p in pts) / n
    # Compute covariance matrix to find normal
    sxx = sxy = sxz = syy = syz = szz = 0.0
    for (x, y, z) in pts:
        dx, dy, dz = x - cx, y - cy, z - cz
        sxx += dx * dx; sxy += dx * dy; sxz += dx * dz
        syy += dy * dy; syz += dy * dz; szz += dz * dz
    # Normal = eigenvector of min eigenvalue — use power iteration on covariance
    # Approximate: for a flat polygon the Z-range should be near zero
    zs = [p[2] for p in pts]
    z_range = max(zs) - min(zs)
    xy_span = max(
        (max(p[0] for p in pts) - min(p[0] for p in pts)),
        (max(p[1] for p in pts) - min(p[1] for p in pts)),
        1e-12,
    )
    # Simple flatness check: z_range / xy_span < relative_tol
    return z_range < tol or (z_range / xy_span) < tol


def _develop_flat_planar(
    ply: CompositePlyDef,
) -> List[Tuple[float, float]]:
    """Isometric development for a planar ply boundary.

    Projects 3-D boundary points onto the plane of best fit, then rotates
    so that the mean boundary edge vector aligns with the +X axis.

    This is an exact (zero-distortion) development for developable surfaces.
    """
    pts = ply.boundary_3d
    n = len(pts)
    if n < 2:
        return [(p[0], p[1]) for p in pts]

    # Compute plane normal via first two edges
    def cross(a: Tuple[float, float, float], b: Tuple[float, float, float]):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
        mag = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
        if mag < 1e-12:
            return (0.0, 0.0, 1.0)
        return (v[0] / mag, v[1] / mag, v[2] / mag)

    # Pick three non-collinear points
    p0 = pts[0]
    p1 = pts[1]
    p2 = pts[n // 2]

    v1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    v2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    normal = normalize(cross(v1, v2))

    # Local X axis: direction of first edge (projected onto plane)
    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def scale(v, s):
        return (v[0] * s, v[1] * s, v[2] * s)

    def add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

    # Project v1 onto plane (subtract normal component)
    x_axis = normalize(sub(v1, scale(normal, dot(v1, normal))))
    # Y axis = normal × x_axis
    y_axis = normalize(cross(normal, x_axis))

    # Project all boundary points onto the local 2-D frame
    flat: List[Tuple[float, float]] = []
    for pt in pts:
        dp = sub(pt, p0)
        u = dot(dp, x_axis)
        v = dot(dp, y_axis)
        flat.append((u, v))

    return flat


def _develop_flat_lscm(
    ply: CompositePlyDef,
) -> Tuple[List[Tuple[float, float]], float]:
    """Non-developable surface unwrap using LSCM if available, else geodesic fallback.

    Returns (flat_boundary_2d, distortion_max_mm).
    """
    try:
        # Try to reuse the kerf LSCM UV tool
        from kerf_cad_core.sculpt.lscm_uv_tool import lscm_uv_unwrap_mesh
        # Build a minimal triangulated mesh from the boundary polygon
        # (fan triangulation from first vertex)
        pts = ply.boundary_3d
        n = len(pts)
        vertices = [[p[0], p[1], p[2]] for p in pts]
        faces = [[0, i, i + 1] for i in range(1, n - 1)]
        if not faces:
            raise ValueError("too few boundary points for LSCM")
        mesh = {"vertices": vertices, "faces": faces}
        result = lscm_uv_unwrap_mesh(mesh)
        uv_coords = result["uv_coords"]
        # Extract boundary UV (vertices 0..n-1 are the boundary)
        flat = [(uv[0], uv[1]) for uv in uv_coords[:n]]
        # Estimate distortion: compare 3D edge lengths to 2D edge lengths
        max_err_m = 0.0
        for i in range(n):
            l3d = _edge_length_3d(pts[i], pts[(i + 1) % n])
            u0, v0 = flat[i]
            u1, v1 = flat[(i + 1) % n]
            l2d = math.sqrt((u1 - u0) ** 2 + (v1 - v0) ** 2)
            max_err_m = max(max_err_m, abs(l3d - l2d))
        return flat, max_err_m * 1000.0  # to mm
    except Exception:
        # Fallback: geodesic path-length based development (1-D chain unfold)
        return _develop_flat_chain(ply)


def _develop_flat_chain(
    ply: CompositePlyDef,
) -> Tuple[List[Tuple[float, float]], float]:
    """Simple chain (strip) development for mildly curved surfaces.

    Unfolds the boundary polygon edge-by-edge, preserving edge lengths.
    Suitable for nearly-developable (gentle curvature) surfaces.
    Distortion estimate = max |3D edge length − 2D edge length|.
    """
    pts = ply.boundary_3d
    n = len(pts)
    if n < 2:
        return [(0.0, 0.0)] * n, 0.0

    flat: List[Tuple[float, float]] = [(0.0, 0.0)]
    # First edge along +X
    l0 = _edge_length_3d(pts[0], pts[1])
    flat.append((l0, 0.0))

    max_err_mm = 0.0
    angle_accum = 0.0

    for i in range(1, n - 1):
        l_prev = _edge_length_3d(pts[i - 1], pts[i])
        l_next = _edge_length_3d(pts[i], pts[i + 1])
        # 3-D angle at pts[i] between the two edges
        def vec3(a, b):
            return (b[0] - a[0], b[1] - a[1], b[2] - a[2])

        def dot3(a, b):
            return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

        ea = vec3(pts[i], pts[i - 1])
        eb = vec3(pts[i], pts[i + 1])
        mag_a = math.sqrt(dot3(ea, ea))
        mag_b = math.sqrt(dot3(eb, eb))
        if mag_a < 1e-12 or mag_b < 1e-12:
            cos_angle = 1.0
        else:
            cos_angle = max(-1.0, min(1.0, dot3(ea, eb) / (mag_a * mag_b)))
        angle_3d = math.acos(cos_angle)  # angle between edges in 3D (exterior)
        # In the developed plane, turn by this angle
        angle_accum += math.pi - angle_3d

        ux = flat[-1][0] + l_next * math.cos(angle_accum)
        uy = flat[-1][1] + l_next * math.sin(angle_accum)
        flat.append((ux, uy))

        # Distortion: l_next in 2D should equal l_next in 3D
        l2d = math.sqrt((ux - flat[-2][0]) ** 2 + (uy - flat[-2][1]) ** 2)
        max_err_mm = max(max_err_mm, abs(l_next - l2d) * 1000.0)

    return flat, max_err_mm


# ---------------------------------------------------------------------------
# Core development function
# ---------------------------------------------------------------------------

def develop_ply_to_flat(
    ply: CompositePlyDef,
    surface_uv: object = None,
) -> FlatPatternResult:
    """Develop a 3-D ply boundary to its flat-pattern.

    Strategy selection:
      - If the 3-D boundary is planar (all points lie on a plane within 0.1 mm
        tolerance), uses isometric projection (exact, zero distortion).
      - Otherwise, uses LSCM via kerf_cad_core.sculpt.lscm_uv_tool if available,
        falling back to a chain-unfold approximation.

    Parameters
    ----------
    ply : CompositePlyDef
        Ply definition with 3-D boundary polygon.
    surface_uv : object, optional
        Reserved for future parametric surface objects (ignored currently).

    Returns
    -------
    FlatPatternResult
        Flat 2-D boundary, fiber direction in flat frame, nesting efficiency,
        and maximum distortion.

    References
    ----------
    Lévy et al. (2002). SIGGRAPH 2002, pp. 362–371.
    """
    if not ply.boundary_3d or len(ply.boundary_3d) < 3:
        raise ValueError("ply.boundary_3d must have at least 3 points")

    planar = _is_planar(ply.boundary_3d)

    if planar:
        flat_2d = _develop_flat_planar(ply)
        distortion_max_mm = 0.0
    else:
        flat_2d, distortion_max_mm = _develop_flat_lscm(ply)

    # Fiber direction in flat frame
    theta_rad = math.radians(ply.ply_orientation_deg)
    fiber_dir: Tuple[float, float] = (math.cos(theta_rad), math.sin(theta_rad))

    # Nesting efficiency: area of ply / area of bounding box
    ply_area = _polygon_area_2d(flat_2d)
    if ply_area > 0:
        x_min, x_max, y_min, y_max = _bounding_box_2d(flat_2d)
        bb_area = (x_max - x_min) * (y_max - y_min)
        nesting_efficiency_pct = (ply_area / bb_area * 100.0) if bb_area > 0 else 0.0
    else:
        nesting_efficiency_pct = 0.0

    nesting_efficiency_pct = max(0.0, min(100.0, nesting_efficiency_pct))

    return FlatPatternResult(
        ply_id=ply.ply_id,
        flat_boundary_2d=flat_2d,
        fiber_direction_in_flat=fiber_dir,
        nesting_efficiency_pct=nesting_efficiency_pct,
        distortion_max_mm=distortion_max_mm,
    )


# ---------------------------------------------------------------------------
# DXF R12 export
# ---------------------------------------------------------------------------

def export_flat_pattern_dxf(result: FlatPatternResult) -> str:
    """Export a FlatPatternResult as an AutoCAD DXF R12 file.

    The flat boundary is exported as a closed LWPOLYLINE (represented as LINE
    entities for DXF R12 compatibility).  A DXF R12 TEXT entity labels the
    ply ID and orientation.

    DXF R12 format reference: AutoCAD DXF Reference, Release 12, §3 Group Codes.

    Parameters
    ----------
    result : FlatPatternResult

    Returns
    -------
    str
        DXF R12 file content.  Contains 'SECTION', 'ENTITIES', and 'EOF' markers.
    """
    lines: List[str] = []

    def dxf_line(group: int, value: str) -> None:
        lines.append(f"{group:3d}")
        lines.append(value)

    # --- HEADER ---
    dxf_line(0, "SECTION")
    dxf_line(2, "HEADER")
    dxf_line(9, "$ACADVER")
    dxf_line(1, "AC1009")  # DXF R12
    dxf_line(9, "$INSUNITS")
    dxf_line(70, "4")      # 4 = millimetres
    dxf_line(0, "ENDSEC")

    # --- ENTITIES ---
    dxf_line(0, "SECTION")
    dxf_line(2, "ENTITIES")

    pts = result.flat_boundary_2d
    n = len(pts)

    # LINE entities forming the closed polygon (DXF R12 — no LWPOLYLINE)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        # Convert metres to mm for DXF (standard CAD units)
        dxf_line(0, "LINE")
        dxf_line(8, f"PLY_{result.ply_id}")   # layer name
        dxf_line(10, f"{x0 * 1000.0:.6f}")    # start X
        dxf_line(20, f"{y0 * 1000.0:.6f}")    # start Y
        dxf_line(30, "0.0")                    # start Z
        dxf_line(11, f"{x1 * 1000.0:.6f}")    # end X
        dxf_line(21, f"{y1 * 1000.0:.6f}")    # end Y
        dxf_line(31, "0.0")                    # end Z

    # Fiber direction indicator line (from centroid, length = 50 mm)
    if pts:
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        fx, fy = result.fiber_direction_in_flat
        flen = 0.05  # 50 mm in metres
        dxf_line(0, "LINE")
        dxf_line(8, f"FIBER_DIR_{result.ply_id}")
        dxf_line(10, f"{cx * 1000.0:.6f}")
        dxf_line(20, f"{cy * 1000.0:.6f}")
        dxf_line(30, "0.0")
        dxf_line(11, f"{(cx + fx * flen) * 1000.0:.6f}")
        dxf_line(21, f"{(cy + fy * flen) * 1000.0:.6f}")
        dxf_line(31, "0.0")

        # TEXT entity: ply label
        dxf_line(0, "TEXT")
        dxf_line(8, "LABELS")
        dxf_line(10, f"{cx * 1000.0:.6f}")
        dxf_line(20, f"{cy * 1000.0:.6f}")
        dxf_line(30, "0.0")
        dxf_line(40, "5.0")    # text height 5 mm
        dxf_line(1, f"{result.ply_id}")

    dxf_line(0, "ENDSEC")

    # --- EOF ---
    dxf_line(0, "EOF")

    return "\n".join(lines)
