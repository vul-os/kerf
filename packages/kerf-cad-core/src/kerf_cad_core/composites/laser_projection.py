"""
kerf_cad_core.composites.laser_projection — Laser projection export for composite ply layup.

Generates laser projector template files from 3-D ply boundaries. Supports:
  - Virtek IRIS ALS XML format (IRIS 5D operator's guide, publicly available)
  - Aligned Vision HFL semicolon-delimited format (Aligned Vision user manual)

Laser projection guides operators in manually laying composite plies by projecting
bright outlines onto the mold tool surface, replacing paper templates.

References
----------
Aligned Vision LP5 / LPS5 Laser Projection System User Manual (public).
    https://alignedvision.com — DataSheet series, Rev D.
Virtek IRIS 5D Operator's Guide, Chapter 4: Template Authoring (public).
    https://virtek.com — IRIS 5D product documentation.

Author: imranparuk
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any

from kerf_cad_core.composites.afp_atl_path import CompositePlyDef


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LaserProjectorSpec:
    """Laser projector mounting configuration.

    Attributes
    ----------
    name : str
        Projector model, e.g. 'Aligned Vision LPS5', 'Virtek IRIS 5D'.
    position : (x, y, z)
        Projector mounting position in the mold coordinate frame (metres).
    aim_direction : (dx, dy, dz)
        Unit vector pointing from the projector toward the mold surface.
    fov_deg : (half_angle_x, half_angle_y)
        Projector cone half-angles in degrees (field of view in X and Y).
    range_m : float
        Maximum working distance in metres.
    """
    name: str
    position: Tuple[float, float, float]
    aim_direction: Tuple[float, float, float]
    fov_deg: Tuple[float, float]
    range_m: float


@dataclass
class LaserProjectionFile:
    """A compiled laser projection template for one or more plies.

    Attributes
    ----------
    projector : LaserProjectorSpec
        The projector configuration this template targets.
    template_segments : list of dicts
        Each dict: {'start_3d': (x,y,z), 'end_3d': (x,y,z),
                    'color': str (hex), 'dwell_us': int,
                    'ply_id': str}.
    file_format : str
        'ALS_VRT' for Virtek IRIS ALS XML, 'LASERVISION_HFL' for Aligned Vision HFL.
    """
    projector: LaserProjectorSpec
    template_segments: List[Dict[str, Any]]
    file_format: str


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Return normalised copy of vector v. Returns v unchanged if zero-length."""
    mag = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if mag < 1e-12:
        return v
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def _dot(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _transform_to_projector_frame(
    pt_world: Tuple[float, float, float],
    projector: LaserProjectorSpec,
) -> Tuple[float, float, float]:
    """Transform a world-frame 3-D point into the projector's local frame.

    The projector local frame is defined by:
      - Origin: projector.position
      - Z-axis: projector.aim_direction (normalised)
      - X-axis: arbitrary perpendicular to aim_direction
      - Y-axis: Z × X

    Returns (x_proj, y_proj, depth) — depth is distance along aim axis.
    """
    aim = _normalize(projector.aim_direction)
    # Build an arbitrary orthonormal frame
    # Pick X-axis perpendicular to aim
    if abs(aim[0]) < 0.9:
        ref = (1.0, 0.0, 0.0)
    else:
        ref = (0.0, 1.0, 0.0)
    # x_axis = aim × ref, normalised
    x_ax = (
        aim[1] * ref[2] - aim[2] * ref[1],
        aim[2] * ref[0] - aim[0] * ref[2],
        aim[0] * ref[1] - aim[1] * ref[0],
    )
    x_ax = _normalize(x_ax)
    # y_axis = aim × x_axis
    y_ax = (
        aim[1] * x_ax[2] - aim[2] * x_ax[1],
        aim[2] * x_ax[0] - aim[0] * x_ax[2],
        aim[0] * x_ax[1] - aim[1] * x_ax[0],
    )
    y_ax = _normalize(y_ax)

    # Vector from projector to point
    dp = (
        pt_world[0] - projector.position[0],
        pt_world[1] - projector.position[1],
        pt_world[2] - projector.position[2],
    )
    x_proj = _dot(dp, x_ax)
    y_proj = _dot(dp, y_ax)
    depth = _dot(dp, aim)
    return (x_proj, y_proj, depth)


def _ply_color_by_index(index: int) -> str:
    """Assign a deterministic hex color to ply index for Virtek color coding."""
    colors = [
        "#FF0000",  # Red   — 0°
        "#00FF00",  # Green — 90°
        "#0000FF",  # Blue  — +45°
        "#FFFF00",  # Yellow — -45°
        "#FF00FF",  # Magenta — +60°
        "#00FFFF",  # Cyan   — -60°
        "#FF8800",  # Orange — 30°
        "#8800FF",  # Purple — -30°
    ]
    return colors[index % len(colors)]


# ---------------------------------------------------------------------------
# Core generation function
# ---------------------------------------------------------------------------

def generate_laser_projection(
    plies: List[CompositePlyDef],
    projector: LaserProjectorSpec,
) -> LaserProjectionFile:
    """Generate a laser projection template from a list of composite plies.

    For each ply, the closed 3-D boundary is broken into line segments and
    projected into the projector coordinate frame.  Each segment is assigned a
    color derived from the ply index and a default dwell time.

    The output LaserProjectionFile can be serialised to Virtek ALS XML or
    Aligned Vision HFL format via the export functions below.

    Parameters
    ----------
    plies : list of CompositePlyDef
        Ply definitions whose boundary_3d polygons will be projected.
    projector : LaserProjectorSpec
        Mounting configuration of the laser projector.

    Returns
    -------
    LaserProjectionFile

    References
    ----------
    Aligned Vision LPS5 User Manual, §4 Template Setup.
    Virtek IRIS 5D Operator's Guide, §4 Template Authoring.
    """
    if not plies:
        raise ValueError("plies list must not be empty")

    segments: List[Dict[str, Any]] = []

    for ply_index, ply in enumerate(plies):
        boundary = ply.boundary_3d
        if len(boundary) < 2:
            continue
        color = _ply_color_by_index(ply_index)
        n = len(boundary)
        for i in range(n):
            pt_a = boundary[i]
            pt_b = boundary[(i + 1) % n]
            # Project to projector frame (for FOV-clip metadata)
            _a_proj = _transform_to_projector_frame(pt_a, projector)
            _b_proj = _transform_to_projector_frame(pt_b, projector)
            segments.append({
                "start_3d": pt_a,
                "end_3d": pt_b,
                "start_proj": _a_proj,
                "end_proj": _b_proj,
                "color": color,
                "dwell_us": 100,        # 100 µs dwell per segment (typical)
                "ply_id": ply.ply_id,
                "ply_orientation_deg": ply.ply_orientation_deg,
            })

    if not segments:
        raise ValueError("No valid boundary segments generated from plies")

    return LaserProjectionFile(
        projector=projector,
        template_segments=segments,
        file_format="ALS_VRT",
    )


# ---------------------------------------------------------------------------
# Virtek IRIS ALS XML export
# ---------------------------------------------------------------------------

def export_virtek_als(file: LaserProjectionFile) -> str:
    """Serialise a LaserProjectionFile to Virtek IRIS ALS XML format.

    The Virtek ALS (Automated Layup System) XML format groups segments by ply
    into <PlyTemplate> elements inside a <LaserTemplate> root element.  Coordinates
    are in the projector's local frame (mm).

    Format reference: Virtek IRIS 5D Operator's Guide (public), §4 Template Authoring.

    Parameters
    ----------
    file : LaserProjectionFile

    Returns
    -------
    str
        Well-formed XML string starting with '<?xml version="1.0"...'.
    """
    # Group segments by ply_id
    ply_segments: Dict[str, List[Dict[str, Any]]] = {}
    for seg in file.template_segments:
        pid = seg.get("ply_id", "UNKNOWN")
        ply_segments.setdefault(pid, []).append(seg)

    root = ET.Element("LaserTemplate")
    root.set("version", "2.0")
    root.set("generator", "kerf-cad-core")
    root.set(
        "projector",
        f"{file.projector.name}  pos=({file.projector.position[0]:.3f},"
        f"{file.projector.position[1]:.3f},{file.projector.position[2]:.3f})",
    )

    proj_el = ET.SubElement(root, "Projector")
    proj_el.set("name", file.projector.name)
    proj_el.set("posX", f"{file.projector.position[0] * 1000.0:.3f}")
    proj_el.set("posY", f"{file.projector.position[1] * 1000.0:.3f}")
    proj_el.set("posZ", f"{file.projector.position[2] * 1000.0:.3f}")
    proj_el.set("fovX_deg", f"{file.projector.fov_deg[0]:.2f}")
    proj_el.set("fovY_deg", f"{file.projector.fov_deg[1]:.2f}")
    proj_el.set("range_m", f"{file.projector.range_m:.3f}")

    for ply_id, segs in ply_segments.items():
        ply_el = ET.SubElement(root, "PlyTemplate")
        ply_el.set("plyId", ply_id)
        if segs:
            ply_el.set("orientation_deg", str(segs[0].get("ply_orientation_deg", 0.0)))
            ply_el.set("color", segs[0].get("color", "#FF0000"))

        for seg in segs:
            seg_el = ET.SubElement(ply_el, "Segment")
            sx, sy, sz = seg["start_3d"]
            ex, ey, ez = seg["end_3d"]
            # Virtek coordinates in mm
            seg_el.set("x1", f"{sx * 1000.0:.4f}")
            seg_el.set("y1", f"{sy * 1000.0:.4f}")
            seg_el.set("z1", f"{sz * 1000.0:.4f}")
            seg_el.set("x2", f"{ex * 1000.0:.4f}")
            seg_el.set("y2", f"{ey * 1000.0:.4f}")
            seg_el.set("z2", f"{ez * 1000.0:.4f}")
            seg_el.set("color", seg.get("color", "#FF0000"))
            seg_el.set("dwellUs", str(seg.get("dwell_us", 100)))

    # Serialise
    tree_str = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tree_str


# ---------------------------------------------------------------------------
# Aligned Vision HFL export
# ---------------------------------------------------------------------------

def export_aligned_vision_hfl(file: LaserProjectionFile) -> str:
    """Serialise a LaserProjectionFile to Aligned Vision HFL format.

    HFL (Holographic Feature List) is Aligned Vision's semicolon-delimited
    segment format used by the LPS5 and LP5 systems.  Each line represents one
    laser segment:

        PLY_ID;SEG_IDX;X1_mm;Y1_mm;Z1_mm;X2_mm;Y2_mm;Z2_mm;COLOR;DWELL_US

    Format reference: Aligned Vision LPS5 User Manual, Appendix B (public).

    Parameters
    ----------
    file : LaserProjectionFile

    Returns
    -------
    str
        HFL content with one segment per line.
    """
    lines: List[str] = []
    lines.append(
        "# Aligned Vision HFL — generated by kerf-cad-core"
    )
    lines.append(
        f"# Projector: {file.projector.name}  "
        f"pos=({file.projector.position[0]:.3f},"
        f"{file.projector.position[1]:.3f},{file.projector.position[2]:.3f}) m"
    )
    lines.append("# PLY_ID;SEG_IDX;X1_mm;Y1_mm;Z1_mm;X2_mm;Y2_mm;Z2_mm;COLOR;DWELL_US")

    for idx, seg in enumerate(file.template_segments):
        sx, sy, sz = seg["start_3d"]
        ex, ey, ez = seg["end_3d"]
        ply_id = seg.get("ply_id", "UNKNOWN")
        color = seg.get("color", "#FF0000")
        dwell = seg.get("dwell_us", 100)
        lines.append(
            f"{ply_id};{idx};"
            f"{sx * 1000.0:.4f};{sy * 1000.0:.4f};{sz * 1000.0:.4f};"
            f"{ex * 1000.0:.4f};{ey * 1000.0:.4f};{ez * 1000.0:.4f};"
            f"{color};{dwell}"
        )

    return "\n".join(lines)
