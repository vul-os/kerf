"""
pcb_3d_clearance.py — 3D PCB body-clearance DRC and STEP component import.

Provides:
  1. STEP component body import — parse a minimal STEP AP214/AP242 file for a
     component body and extract its bounding-box dimensions (X, Y, Z in mm).
     Delegates to pythonOCC when available; returns parametric bbox otherwise.

  2. Component placement 3D model — represents one placed component in the
     board coordinate system as an axis-aligned bounding box (AABB) with
     optional Z-rotation.

  3. Board 3D clearance DRC — check all pairs of placed component bodies for
     3D body-to-body clearance violations (Altium 3D Body Clearance Rule §7.4).

References
----------
Altium Designer 3D PCB Design Guide:
  https://www.altium.com/documentation/altium-designer/3d-pcb-design
  §7.4 "3D Body Clearance DRC Rule"

IPC-7351B §4.5: keep-out zone requirements for component bodies.
IPC-7711/7721 §3: rework clearance recommendations.
STEP AP214 ISO 10303-214 / AP242 ISO 10303-242 §4.3: assembly geometry.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ─── Data models ──────────────────────────────────────────────────────────────


@dataclass
class ComponentBody3D:
    """AABB representation of a placed component body in board coordinates.

    Altium §7.4: component bodies are modelled as either exact imported STEP
    solids or parametric bounding boxes.  This class covers both cases by
    using the AABB of the body extents.

    Coordinates:
        x_mm, y_mm  — board-plane centre of the component body (mm)
        z_bot_mm    — bottom face Z (= 0 for top-side, ≈ -thickness for bottom)
        z_top_mm    — top face Z (= body height above board surface)
        width_mm    — body dimension along the X axis (before rotation)
        height_mm   — body dimension along the Y axis (before rotation)
        rotation_deg — Z-rotation applied to the footprint (deg)
        refdes      — component reference designator
        footprint   — footprint name used for parametric sizing fallback
        step_file   — optional path to the STEP model (may be None)
    """

    refdes: str
    x_mm: float
    y_mm: float
    z_bot_mm: float
    z_top_mm: float
    width_mm: float
    height_mm: float
    rotation_deg: float = 0.0
    footprint: str = ""
    step_file: str | None = None


@dataclass
class ClearanceViolation:
    """A 3D body-clearance DRC violation between two component bodies."""

    comp_a: str
    """Reference designator of the first component."""

    comp_b: str
    """Reference designator of the second component."""

    gap_mm: float
    """Minimum distance between the two AABB hulls (mm).
    Negative → bodies interpenetrate."""

    required_mm: float
    """Required clearance (mm) from the active 3D clearance rule."""

    violation_type: str = "body_clearance"
    """'body_clearance' | 'body_intersection'."""


# ─── STEP bounding-box extractor ──────────────────────────────────────────────


def parse_step_body_bbox(
    step_text: str,
) -> dict[str, float]:
    """
    Extract the approximate bounding-box dimensions of the first solid body
    in a STEP AP214/AP242 text blob.

    When pythonOCC is available, the accurate AABB is computed from the B-rep
    geometry (OCC.Core.Bnd + BRepBndLib).  When OCC is not installed, a
    regex scan for CARTESIAN_POINT entities is used to estimate the bbox.

    Parameters
    ----------
    step_text : str
        Full content of a STEP file as a string.

    Returns
    -------
    dict with keys:
        ok      : bool
        x_mm    : float — bounding-box X dimension
        y_mm    : float — bounding-box Y dimension
        z_mm    : float — bounding-box Z dimension (height above origin)
        method  : 'occ' | 'cartesian_point_scan' | 'fallback'
        n_points: int   — number of CARTESIAN_POINT entities found
    """
    # ── Try pythonOCC first ────────────────────────────────────────────────
    try:
        from OCC.Core.STEPControl import STEPControl_Reader  # type: ignore
        from OCC.Core.BRepBndLib import brepbndlib  # type: ignore
        from OCC.Core.Bnd import Bnd_Box  # type: ignore
        from OCC.Core.IFSelect import IFSelect_RetDone  # type: ignore
        import tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".stp", mode="w", delete=False) as f:
            f.write(step_text)
            tmp_path = f.name
        try:
            reader = STEPControl_Reader()
            status = reader.ReadFile(tmp_path)
            if status == IFSelect_RetDone:
                reader.TransferRoots()
                shape = reader.OneShape()
                bbox = Bnd_Box()
                brepbndlib.Add(shape, bbox)
                xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
                return {
                    "ok": True,
                    "x_mm": round(abs(xmax - xmin), 4),
                    "y_mm": round(abs(ymax - ymin), 4),
                    "z_mm": round(abs(zmax - zmin), 4),
                    "method": "occ",
                    "n_points": 0,
                }
        finally:
            os.unlink(tmp_path)
    except Exception:
        pass  # OCC not available or parse failed — fall through

    # ── Regex scan: collect all CARTESIAN_POINT coordinates ──────────────
    # STEP syntax: #N = CARTESIAN_POINT('label',(x.,y.,z.));
    pattern = re.compile(
        r"CARTESIAN_POINT\s*\([^,]*,\s*\(([^)]+)\)\s*\)",
        re.IGNORECASE,
    )
    points: list[tuple[float, float, float]] = []
    for m in pattern.finditer(step_text):
        coords_str = m.group(1)
        parts = coords_str.split(",")
        if len(parts) >= 3:
            try:
                x = float(parts[0].strip())
                y = float(parts[1].strip())
                z = float(parts[2].strip())
                points.append((x, y, z))
            except ValueError:
                pass

    if len(points) >= 2:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]
        x_dim = max(xs) - min(xs)
        y_dim = max(ys) - min(ys)
        z_dim = max(zs) - min(zs)
        # Ensure minimum 0.1 mm for degenerate geometry
        return {
            "ok": True,
            "x_mm": round(max(x_dim, 0.1), 4),
            "y_mm": round(max(y_dim, 0.1), 4),
            "z_mm": round(max(z_dim, 0.1), 4),
            "method": "cartesian_point_scan",
            "n_points": len(points),
        }

    # ── Final fallback: parametric from footprint name in STEP description ─
    # Try to extract board/body dimensions from FILE_DESCRIPTION string
    desc_match = re.search(r"FILE_DESCRIPTION\s*\(\s*\('([^']+)'", step_text)
    name = desc_match.group(1) if desc_match else ""

    # Heuristic sizes by footprint family (IPC-7351B Table 3)
    fallback = {"x_mm": 2.0, "y_mm": 2.0, "z_mm": 1.5}
    for fam, dims in [
        ("0402", {"x_mm": 1.0, "y_mm": 0.5, "z_mm": 0.35}),
        ("0603", {"x_mm": 1.6, "y_mm": 0.8, "z_mm": 0.45}),
        ("0805", {"x_mm": 2.0, "y_mm": 1.25, "z_mm": 0.6}),
        ("1206", {"x_mm": 3.2, "y_mm": 1.6, "z_mm": 0.7}),
        ("SOT23", {"x_mm": 2.9, "y_mm": 1.6, "z_mm": 1.1}),
        ("SOIC8", {"x_mm": 5.0, "y_mm": 4.0, "z_mm": 1.75}),
        ("QFN", {"x_mm": 4.0, "y_mm": 4.0, "z_mm": 1.0}),
        ("BGA", {"x_mm": 7.0, "y_mm": 7.0, "z_mm": 1.4}),
        ("TQFP", {"x_mm": 7.0, "y_mm": 7.0, "z_mm": 1.6}),
    ]:
        if fam.lower() in name.lower() or fam.lower() in step_text[:500].lower():
            fallback = dims
            break

    return {
        "ok": True,
        "x_mm": fallback["x_mm"],
        "y_mm": fallback["y_mm"],
        "z_mm": fallback["z_mm"],
        "method": "fallback",
        "n_points": 0,
    }


# ─── AABB clearance check ──────────────────────────────────────────────────────


def _body_aabb(comp: ComponentBody3D) -> tuple[float, float, float, float, float, float]:
    """Return (xmin, xmax, ymin, ymax, zmin, zmax) in mm for a component body.

    The XY footprint is the body bounding box rotated about (x_mm, y_mm).
    For clearance checks the worst-case (axis-aligned) AABB of the rotated
    box is used (conservative — same assumption Altium makes for the fast
    DRC pass before using the full STEP-solid check).

    References: Altium 3D DRC §7.4 "Bounding Box Approximation".
    """
    # Half dimensions
    hw = comp.width_mm / 2.0
    hh = comp.height_mm / 2.0

    # Rotated AABB (worst-case axis-aligned extent after Z rotation)
    rz = math.radians(comp.rotation_deg)
    cos_a = abs(math.cos(rz))
    sin_a = abs(math.sin(rz))

    aabb_half_x = hw * cos_a + hh * sin_a
    aabb_half_y = hw * sin_a + hh * cos_a

    return (
        comp.x_mm - aabb_half_x,
        comp.x_mm + aabb_half_x,
        comp.y_mm - aabb_half_y,
        comp.y_mm + aabb_half_y,
        comp.z_bot_mm,
        comp.z_top_mm,
    )


def _aabb_gap(
    a: tuple[float, float, float, float, float, float],
    b: tuple[float, float, float, float, float, float],
) -> float:
    """Minimum 3D gap between two AABBs.  Negative → overlap/interpenetration.

    Uses the standard AABB separation test:
        gap_i = max(a_lo_i - b_hi_i, b_lo_i - a_hi_i)
    for each axis.  Overall gap = max over all axes (positive → gap, negative → overlap).

    Reference: Gottschalk et al. "OBBTree" §2.1; SIGGRAPH 1996.
    """
    xlo_a, xhi_a, ylo_a, yhi_a, zlo_a, zhi_a = a
    xlo_b, xhi_b, ylo_b, yhi_b, zlo_b, zhi_b = b

    dx = max(xlo_a - xhi_b, xlo_b - xhi_a)
    dy = max(ylo_a - yhi_b, ylo_b - yhi_a)
    dz = max(zlo_a - zhi_b, zlo_b - zhi_a)

    # Each axis: positive = separated on that axis; negative = overlapping
    # Minimum 3D signed gap = the penultimate value:
    #   if all axes have gap > 0 → separated → gap = max(dx, dy, dz) is WRONG
    #   the correct 3D gap for separated AABBs is sqrt(max(0,dx)^2+max(0,dy)^2+max(0,dz)^2)
    # For the Altium-style clearance check (axis-aligned clearance per axis):
    #   use the largest separating axis gap when not overlapping,
    #   and the negative of the smallest overlap when interpenetrating.
    if dx >= 0 and dy >= 0 and dz >= 0:
        # Separated: Euclidean distance between AABB surfaces
        return math.sqrt(dx**2 + dy**2 + dz**2)
    elif dx < 0 and dy < 0 and dz < 0:
        # Fully interpenetrating on all axes: negative gap
        return min(dx, dy, dz)
    else:
        # Partially overlapping — zero gap (in contact)
        return 0.0


def check_3d_clearance(
    components: list[ComponentBody3D],
    min_clearance_mm: float = 0.2,
) -> dict[str, Any]:
    """
    Run a 3D body-clearance DRC check on all component pairs.

    Algorithm
    ---------
    1. Compute the AABB for each component body (conservative rotation envelope).
    2. For each pair (i, j) compute the minimum 3D gap between their AABBs.
    3. Flag pairs where gap < min_clearance_mm as violations.
       Pairs with gap < 0 are flagged as 'body_intersection' (critical).
       Pairs with 0 ≤ gap < min_clearance_mm are flagged as 'body_clearance'.

    Parameters
    ----------
    components : list[ComponentBody3D]
        All placed components on the board.
    min_clearance_mm : float
        Minimum required 3D body clearance (default 0.2 mm = Altium default).
        Reference: Altium 3D Body Clearance Rule §7.4 default = 0.2 mm.

    Returns
    -------
    dict with keys:
        ok              : bool
        violation_count : int
        violations      : list of violation dicts
        component_count : int
        pairs_checked   : int
        min_clearance_mm: float
    """
    if min_clearance_mm < 0:
        return {"ok": False, "reason": "min_clearance_mm must be >= 0"}
    if not isinstance(components, list):
        return {"ok": False, "reason": "components must be a list"}

    violations: list[dict[str, Any]] = []
    n = len(components)
    pairs_checked = 0

    aabbs = [_body_aabb(c) for c in components]

    for i in range(n):
        for j in range(i + 1, n):
            gap = _aabb_gap(aabbs[i], aabbs[j])
            pairs_checked += 1
            if gap < min_clearance_mm:
                vtype = "body_intersection" if gap < 0 else "body_clearance"
                violations.append(
                    {
                        "comp_a": components[i].refdes,
                        "comp_b": components[j].refdes,
                        "gap_mm": round(gap, 4),
                        "required_mm": min_clearance_mm,
                        "violation_type": vtype,
                        "severity": "error" if gap < 0 else "warning",
                        "message": (
                            f"3D body clearance violation: {components[i].refdes} ↔ "
                            f"{components[j].refdes}: gap={gap:.3f} mm "
                            f"(required ≥ {min_clearance_mm} mm) [{vtype}]"
                        ),
                    }
                )

    return {
        "ok": True,
        "violation_count": len(violations),
        "violations": violations,
        "component_count": n,
        "pairs_checked": pairs_checked,
        "min_clearance_mm": min_clearance_mm,
        "reference": "Altium 3D Body Clearance Rule §7.4; IPC-7351B §4.5",
    }


# ─── CircuitJSON → ComponentBody3D extraction ─────────────────────────────────


def extract_component_bodies(
    circuit_json: list[dict],
    board_thickness_mm: float = 1.6,
) -> list[ComponentBody3D]:
    """
    Extract ComponentBody3D objects from a CircuitJSON array.

    Reuses the same geometry extraction logic as board_step and idf_export
    (_collect_placed_components / _estimate_body_size) for consistency.

    Parameters
    ----------
    circuit_json:       Parsed CircuitJSON array.
    board_thickness_mm: PCB substrate thickness (default 1.6 mm FR4).

    Returns
    -------
    List of ComponentBody3D, one per placed pcb_component.
    """
    from kerf_electronics.fab.board_step import _collect_placed_components

    placed = _collect_placed_components(circuit_json)
    bodies: list[ComponentBody3D] = []

    for comp in placed:
        side = comp.get("side", "top")
        bw = float(comp.get("body_w", 2.0))
        bh = float(comp.get("body_h", 2.0))
        bz = float(comp.get("body_z", 1.5))
        rotation = float(comp.get("rotation_deg", 0.0))

        if side == "top":
            z_bot = board_thickness_mm
            z_top = board_thickness_mm + bz
        else:
            # Bottom side: body hangs below the board substrate
            z_bot = -bz
            z_top = 0.0

        bodies.append(
            ComponentBody3D(
                refdes=comp.get("refdes", "?"),
                x_mm=float(comp.get("x", 0.0)),
                y_mm=float(comp.get("y", 0.0)),
                z_bot_mm=z_bot,
                z_top_mm=z_top,
                width_mm=bw,
                height_mm=bh,
                rotation_deg=rotation,
                footprint=comp.get("footprint", ""),
                step_file=comp.get("step_model"),
            )
        )

    return bodies


# ─── LLM tools ────────────────────────────────────────────────────────────────

# ── Tool 1: pcb_3d_clearance_check ──────────────────────────────────────────

_CLEARANCE_CHECK_SPEC = ToolSpec(
    name="pcb_3d_clearance_check",
    description=(
        "Run a 3D component-body clearance DRC on a CircuitJSON PCB board.\n\n"
        "Each placed component is represented as a 3D axis-aligned bounding box "
        "(AABB) following Altium 3D Body Clearance Rule §7.4 + IPC-7351B §4.5.\n"
        "Returns a list of clearance violations: component pairs whose bodies "
        "are closer than min_clearance_mm (default 0.2 mm = Altium default).\n\n"
        "Violation types:\n"
        "  body_intersection (error)  — AABBs interpenetrate (gap < 0)\n"
        "  body_clearance (warning)   — gap < min_clearance_mm but ≥ 0\n\n"
        "Input: { circuit_json, min_clearance_mm?, board_thickness_mm? }\n"
        "Returns: { ok, violation_count, violations:[{comp_a, comp_b, gap_mm, "
        "required_mm, violation_type, severity, message}], component_count, "
        "pairs_checked }"
    ),
    input_schema={
        "type": "object",
        "required": ["circuit_json"],
        "properties": {
            "circuit_json": {
                "type": "array",
                "description": "Parsed CircuitJSON array (tscircuit PCB data model).",
                "items": {"type": "object"},
            },
            "min_clearance_mm": {
                "type": "number",
                "description": (
                    "Minimum 3D body-to-body clearance (mm). "
                    "Default 0.2 mm (Altium 3D Body Clearance Rule §7.4 default). "
                    "IPC-7711/7721 §3 recommends ≥ 0.2 mm for rework clearance."
                ),
            },
            "board_thickness_mm": {
                "type": "number",
                "description": "PCB substrate thickness in mm (default 1.6 mm).",
            },
        },
    },
)


@register(_CLEARANCE_CHECK_SPEC, write=False)
async def pcb_3d_clearance_check(ctx: Any, args: bytes) -> str:
    import json

    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    if not isinstance(circuit_json, list):
        return err_payload("circuit_json must be an array", "BAD_ARGS")

    min_clearance_mm = float(a.get("min_clearance_mm", 0.2))
    board_thickness_mm = float(a.get("board_thickness_mm", 1.6))

    try:
        bodies = extract_component_bodies(circuit_json, board_thickness_mm=board_thickness_mm)
        result = check_3d_clearance(bodies, min_clearance_mm=min_clearance_mm)
    except Exception as exc:
        return err_payload(f"3D clearance check failed: {exc}", "CLEARANCE_ERROR")

    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "CLEARANCE_ERROR")
    return ok_payload(result)


# ── Tool 2: pcb_step_import_body ─────────────────────────────────────────────

_STEP_IMPORT_SPEC = ToolSpec(
    name="pcb_step_import_body",
    description=(
        "Import a STEP file and extract the component body bounding-box "
        "dimensions (X, Y, Z in mm) for use in 3D PCB clearance DRC.\n\n"
        "When pythonOCC is installed, accurate solid geometry is parsed via "
        "STEPControl_Reader + Bnd_Box.  Without OCC, CARTESIAN_POINT entities "
        "in the STEP text are scanned to estimate the bbox.\n\n"
        "Typical use: import a vendor STEP model, get its X/Y/Z dims, then "
        "create a ComponentBody3D for the clearance check.\n\n"
        "Reference: STEP AP214 ISO 10303-214 §4.3 / AP242 ISO 10303-242 §4.3.\n\n"
        "Input: { step_text }\n"
        "Returns: { ok, x_mm, y_mm, z_mm, method, n_points }"
    ),
    input_schema={
        "type": "object",
        "required": ["step_text"],
        "properties": {
            "step_text": {
                "type": "string",
                "description": (
                    "Full STEP file text content (ISO-10303-21 format). "
                    "May be AP214 or AP242."
                ),
            },
        },
    },
)


@register(_STEP_IMPORT_SPEC, write=False)
async def pcb_step_import_body(ctx: Any, args: bytes) -> str:
    import json

    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    step_text = a.get("step_text")
    if not isinstance(step_text, str) or not step_text.strip():
        return err_payload("step_text must be a non-empty string", "BAD_ARGS")

    try:
        result = parse_step_body_bbox(step_text)
    except Exception as exc:
        return err_payload(f"STEP import failed: {exc}", "STEP_IMPORT_ERROR")

    if not result.get("ok"):
        return err_payload(result.get("reason", "STEP parse failed"), "STEP_IMPORT_ERROR")
    return ok_payload(result)


# ─── TOOLS manifest ────────────────────────────────────────────────────────────

TOOLS = [
    (_CLEARANCE_CHECK_SPEC.name, _CLEARANCE_CHECK_SPEC, pcb_3d_clearance_check),
    (_STEP_IMPORT_SPEC.name, _STEP_IMPORT_SPEC, pcb_step_import_body),
]
