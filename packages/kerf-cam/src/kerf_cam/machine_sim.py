"""
kerf_cam.machine_sim — Kinematic machine simulation and collision detection.

Overview
--------
Models a simplified 5-axis machine as a hierarchy of rigid bodies (components),
each positioned by the machine's joint values (X, Y, Z linear + A, B rotary).
Each component is represented as an Axis-Aligned Bounding Box (AABB) in
*machine home* (all joints = 0) coordinates.  For each toolpath point we:

  1. Compute the forward kinematics using the same head-table model used by
     kerf_cam.five_axis.gcode_constant_tilt:
       A  — rotation around X axis (table tilt)
       B  — rotation around Y axis (table tilt / head swing)
       X/Y/Z — linear table/spindle offsets

  2. Transform each component AABB by the joint-specific FK transform to find
     its position at that toolpath point.

  3. Perform pairwise AABB overlap tests between *incompatible* pairs
     (e.g. tool-holder vs table, spindle vs fixture).

  4. Report all collision events: {point_index, x, y, z, a_deg, b_deg,
     component_a, component_b, overlap_mm}.

Machine Geometry (default — generic 3-axis VMC with A/B head-table option)
---------------------------------------------------------------------------
  SPINDLE_HEAD   : static head housing — AABB above Z=0, follows linear Z move
  TOOL_HOLDER    : collet + holder — extends below spindle
  TABLE          : flat worktable — stays at Y=0, rotates with A/B
  FIXTURE_STOCK  : bounding box of the workpiece on the table

All dimensions in mm, same coordinate system as the toolpath (WCS origin at
part datum).  Default parameters approximate a small VMC (e.g. Haas Mini Mill).

References
----------
[1] Held, M. (1991). On the Computational Geometry of Pocket Machining.
    Lecture Notes in Computer Science, Springer.
[2] Suh, S.-H., Kang, S.-K., Chung, D.-H., Stroud, I. (2008).
    Theory and Design of CNC Systems. Springer.
    Chapter 4 — Kinematics of Machine Tools.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

try:
    from kerf_cam.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    try:
        from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------

@dataclass
class AABB:
    """Axis-aligned bounding box in 3-D space (mm)."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    def overlaps(self, other: "AABB") -> bool:
        return (
            self.x_min < other.x_max and self.x_max > other.x_min and
            self.y_min < other.y_max and self.y_max > other.y_min and
            self.z_min < other.z_max and self.z_max > other.z_min
        )

    def overlap_depth(self, other: "AABB") -> float:
        """Return the minimum penetration depth (mm), 0 if no overlap."""
        dx = min(self.x_max, other.x_max) - max(self.x_min, other.x_min)
        dy = min(self.y_max, other.y_max) - max(self.y_min, other.y_min)
        dz = min(self.z_max, other.z_max) - max(self.z_min, other.z_min)
        if dx <= 0 or dy <= 0 or dz <= 0:
            return 0.0
        return min(dx, dy, dz)

    def translate(self, tx: float, ty: float, tz: float) -> "AABB":
        return AABB(
            self.x_min + tx, self.x_max + tx,
            self.y_min + ty, self.y_max + ty,
            self.z_min + tz, self.z_max + tz,
        )

    def center(self) -> Tuple[float, float, float]:
        return (
            (self.x_min + self.x_max) / 2,
            (self.y_min + self.y_max) / 2,
            (self.z_min + self.z_max) / 2,
        )


def _rot_x(pt: Tuple[float, float, float], a_rad: float) -> Tuple[float, float, float]:
    """Rotate point around X axis by a_rad."""
    x, y, z = pt
    c, s = math.cos(a_rad), math.sin(a_rad)
    return x, y * c - z * s, y * s + z * c


def _rot_y(pt: Tuple[float, float, float], b_rad: float) -> Tuple[float, float, float]:
    """Rotate point around Y axis by b_rad."""
    x, y, z = pt
    c, s = math.cos(b_rad), math.sin(b_rad)
    return x * c + z * s, y, -x * s + z * c


def _rotate_aabb(aabb: AABB, a_rad: float, b_rad: float) -> AABB:
    """
    Rotate an AABB by A (around X) then B (around Y), return the new enclosing AABB.

    Because rotation changes orientation, we compute all 8 corners and take the
    axis-aligned envelope of the rotated corners.
    """
    corners = [
        (aabb.x_min, aabb.y_min, aabb.z_min),
        (aabb.x_max, aabb.y_min, aabb.z_min),
        (aabb.x_min, aabb.y_max, aabb.z_min),
        (aabb.x_max, aabb.y_max, aabb.z_min),
        (aabb.x_min, aabb.y_min, aabb.z_max),
        (aabb.x_max, aabb.y_min, aabb.z_max),
        (aabb.x_min, aabb.y_max, aabb.z_max),
        (aabb.x_max, aabb.y_max, aabb.z_max),
    ]
    rotated = [_rot_y(_rot_x(c, a_rad), b_rad) for c in corners]
    xs = [p[0] for p in rotated]
    ys = [p[1] for p in rotated]
    zs = [p[2] for p in rotated]
    return AABB(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


# ---------------------------------------------------------------------------
# Machine component definitions
# ---------------------------------------------------------------------------

@dataclass
class MachineComponent:
    """
    A rigid machine body.

    home_aabb  : AABB of the component at machine home (all joints = 0), in WCS.
    moves_with : which joint axes move this component.
                 "spindle_xyz" → follows X/Y/Z linear moves.
                 "table_ab"    → follows A/B rotary moves (the table stack).
                 "fixture"     → same as table_ab but represents the stock/fixture.
    name       : human-readable label.
    """
    name: str
    home_aabb: AABB
    moves_with: str  # "spindle_xyz" | "table_ab" | "fixture"

    def aabb_at(
        self,
        x: float, y: float, z: float,
        a_rad: float, b_rad: float,
        table_pivot_z: float = 0.0,
    ) -> AABB:
        """
        Return the AABB of this component at the given joint values.

        For spindle-side components (spindle_xyz):
          Translate by (x, y, z) — the spindle moves in XYZ.

        For table-side components (table_ab, fixture):
          Rotate around the table pivot by A then B, then no linear offset
          (the table is fixed in XY; the stock rotates on the table).

        table_pivot_z : Z of the table surface / rotation centre (mm, default 0).
        """
        if self.moves_with == "spindle_xyz":
            return self.home_aabb.translate(x, y, z)

        # Table-side: rotate around pivot.
        # Shift home AABB so pivot is at origin.
        shifted = self.home_aabb.translate(0, 0, -table_pivot_z)
        rotated = _rotate_aabb(shifted, a_rad, b_rad)
        # Shift back.
        return rotated.translate(0, 0, table_pivot_z)


def default_machine(
    tool_diameter_mm: float = 12.0,
    tool_length_mm: float = 80.0,
    holder_diameter_mm: float = 32.0,
    holder_length_mm: float = 50.0,
    stock_x: float = 100.0,
    stock_y: float = 100.0,
    stock_z: float = 50.0,
    stock_origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> List[MachineComponent]:
    """
    Build a default generic VMC machine model.

    Coordinate system: Z+ up, origin at WCS datum (part zero).

    Components
    ----------
    spindle_head  : large casting above Z = 0.
    tool_holder   : collet / holder, directly below spindle (Z = -holder_length to 0).
    tool          : the cutting tool, below the holder.
    table         : flat slab at Z = -5 to 0.
    fixture_stock : the workpiece bounding box (from stock_origin for stock_x×stock_y×stock_z).
    """
    sx, sy, sz = stock_origin

    components = [
        MachineComponent(
            name="spindle_head",
            home_aabb=AABB(
                x_min=-80, x_max=80,
                y_min=-80, y_max=80,
                z_min=0, z_max=200,
            ),
            moves_with="spindle_xyz",
        ),
        MachineComponent(
            name="tool_holder",
            home_aabb=AABB(
                x_min=-holder_diameter_mm / 2, x_max=holder_diameter_mm / 2,
                y_min=-holder_diameter_mm / 2, y_max=holder_diameter_mm / 2,
                z_min=-holder_length_mm, z_max=0.0,
            ),
            moves_with="spindle_xyz",
        ),
        MachineComponent(
            name="tool",
            home_aabb=AABB(
                x_min=-tool_diameter_mm / 2, x_max=tool_diameter_mm / 2,
                y_min=-tool_diameter_mm / 2, y_max=tool_diameter_mm / 2,
                z_min=-(holder_length_mm + tool_length_mm), z_max=-holder_length_mm,
            ),
            moves_with="spindle_xyz",
        ),
        MachineComponent(
            name="table",
            home_aabb=AABB(
                x_min=-300, x_max=300,
                y_min=-200, y_max=200,
                z_min=-20, z_max=0,
            ),
            moves_with="table_ab",
        ),
        MachineComponent(
            name="fixture_stock",
            home_aabb=AABB(
                x_min=sx, x_max=sx + stock_x,
                y_min=sy, y_max=sy + stock_y,
                z_min=sz, z_max=sz + stock_z,
            ),
            moves_with="fixture",
        ),
    ]
    return components


# ---------------------------------------------------------------------------
# Collision pairs (incompatible pairs that must not touch)
# ---------------------------------------------------------------------------

# Pairs that should never overlap: (name_a, name_b)
_COLLISION_PAIRS = [
    ("tool_holder", "table"),
    ("tool_holder", "fixture_stock"),
    ("spindle_head", "table"),
    ("spindle_head", "fixture_stock"),
    ("tool", "table"),       # tool should not plunge through the table itself
]


# ---------------------------------------------------------------------------
# Kinematic forward solver
# ---------------------------------------------------------------------------

def _extract_joint_values(point: dict) -> Tuple[float, float, float, float, float]:
    """
    Extract (x, y, z, a_deg, b_deg) from a toolpath point dict.

    Accepts keys: x, y, z, a, b, a_deg, b_deg.
    Default A=0, B=0 for 3-axis paths.
    """
    x = float(point.get("x", 0.0))
    y = float(point.get("y", 0.0))
    z = float(point.get("z", 0.0))
    a_deg = float(point.get("a_deg", point.get("a", 0.0)))
    b_deg = float(point.get("b_deg", point.get("b", 0.0)))
    return x, y, z, a_deg, b_deg


def check_collisions(
    toolpath_points: List[dict],
    components: Optional[List[MachineComponent]] = None,
    tool_diameter_mm: float = 12.0,
    tool_length_mm: float = 80.0,
    holder_diameter_mm: float = 32.0,
    holder_length_mm: float = 50.0,
    stock_bounds: Optional[dict] = None,
    table_pivot_z: float = 0.0,
) -> dict:
    """
    Check machine component collisions along the toolpath.

    Parameters
    ----------
    toolpath_points  : list of dicts with keys x, y, z, a_deg (or a), b_deg (or b).
    components       : list of MachineComponent.  If None, builds the default model
                       using tool/stock dimensions.
    tool_diameter_mm : cutter diameter (mm).
    tool_length_mm   : cutter length below holder (mm).
    holder_diameter_mm: tool-holder collet diameter (mm).
    holder_length_mm : tool-holder length (mm).
    stock_bounds     : optional dict with x_min, x_max, y_min, y_max, z_min, z_max.
                       When provided, overrides the default stock AABB.
    table_pivot_z    : Z level of the rotary table pivot (default 0 = table surface).

    Returns
    -------
    dict with:
      collisions         : list of collision event dicts.
      n_points_checked   : int.
      n_collisions       : int.
      max_overlap_mm     : float.
      first_collision    : dict | None.
    """
    stock_origin = (0.0, 0.0, 0.0)
    stock_x, stock_y, stock_z = 100.0, 100.0, 50.0

    if stock_bounds is not None:
        bx_min = float(stock_bounds.get("x_min", 0.0))
        bx_max = float(stock_bounds.get("x_max", 100.0))
        by_min = float(stock_bounds.get("y_min", 0.0))
        by_max = float(stock_bounds.get("y_max", 100.0))
        bz_min = float(stock_bounds.get("z_min", 0.0))
        bz_max = float(stock_bounds.get("z_max", 50.0))
        stock_origin = (bx_min, by_min, bz_min)
        stock_x = bx_max - bx_min
        stock_y = by_max - by_min
        stock_z = bz_max - bz_min

    if components is None:
        components = default_machine(
            tool_diameter_mm=tool_diameter_mm,
            tool_length_mm=tool_length_mm,
            holder_diameter_mm=holder_diameter_mm,
            holder_length_mm=holder_length_mm,
            stock_x=stock_x,
            stock_y=stock_y,
            stock_z=stock_z,
            stock_origin=stock_origin,
        )

    # Build name → component lookup.
    comp_map = {c.name: c for c in components}

    collisions = []

    for idx, pt in enumerate(toolpath_points):
        x, y, z, a_deg, b_deg = _extract_joint_values(pt)
        a_rad = math.radians(a_deg)
        b_rad = math.radians(b_deg)

        # Compute all component AABBs at this joint configuration.
        aabbs: dict[str, AABB] = {}
        for comp in components:
            aabbs[comp.name] = comp.aabb_at(
                x, y, z, a_rad, b_rad, table_pivot_z=table_pivot_z
            )

        # Check each incompatible pair.
        for name_a, name_b in _COLLISION_PAIRS:
            if name_a not in aabbs or name_b not in aabbs:
                continue
            bb_a = aabbs[name_a]
            bb_b = aabbs[name_b]
            depth = bb_a.overlap_depth(bb_b)
            if depth > 1e-6:
                collisions.append({
                    "point_index": idx,
                    "x": round(x, 4),
                    "y": round(y, 4),
                    "z": round(z, 4),
                    "a_deg": round(a_deg, 3),
                    "b_deg": round(b_deg, 3),
                    "component_a": name_a,
                    "component_b": name_b,
                    "overlap_mm": round(depth, 4),
                })

    max_overlap = max((c["overlap_mm"] for c in collisions), default=0.0)
    first = collisions[0] if collisions else None

    return {
        "collisions": collisions,
        "n_points_checked": len(toolpath_points),
        "n_collisions": len(collisions),
        "max_overlap_mm": round(max_overlap, 4),
        "first_collision": first,
        "method": "aabb_kinematic_machine_sim",
    }


# ---------------------------------------------------------------------------
# LLM tool
# ---------------------------------------------------------------------------

_tool_spec_name = "cam_machine_collision_check"

try:
    from kerf_cam._compat import ToolSpec as _TS, err_payload as _ep, ok_payload as _op, register as _reg, ProjectCtx as _PCtx  # noqa
    _TS_class = _TS
except ImportError:
    _TS_class = None

# Build spec outside the try so it is always accessible.
cam_machine_collision_check_spec = None

def _build_spec():
    global cam_machine_collision_check_spec
    try:
        from kerf_cam._compat import ToolSpec
    except ImportError:
        try:
            from kerf_chat.tools.registry import ToolSpec
        except ImportError:
            return
    cam_machine_collision_check_spec = ToolSpec(
        name=_tool_spec_name,
        description=(
            "Check machine component collisions along a 5-axis toolpath. "
            "Models the machine as a set of rigid AABB bodies (spindle head, "
            "tool holder, tool, table, fixture/stock) positioned by kinematic "
            "forward transforms at each joint state (X, Y, Z, A, B). "
            "Detects holder-vs-table, holder-vs-stock, spindle-vs-table, "
            "spindle-vs-stock, and tool-vs-table collisions. "
            "Returns all collision events with overlap depth and joint angles. "
            "Provide toolpath_points as [{x, y, z, a_deg, b_deg}, ...]. "
            "For 3-axis paths omit a_deg/b_deg (defaults to 0)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "toolpath_points": {
                    "type": "array",
                    "description": "List of joint-space points {x,y,z,a_deg,b_deg}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "z": {"type": "number"},
                            "a_deg": {"type": "number"},
                            "b_deg": {"type": "number"},
                        },
                        "required": ["x", "y", "z"],
                    },
                },
                "tool_diameter_mm": {"type": "number", "description": "Tool diameter (mm, default 12)"},
                "tool_length_mm": {"type": "number", "description": "Cutting flute length (mm, default 80)"},
                "holder_diameter_mm": {"type": "number", "description": "Holder collet diameter (mm, default 32)"},
                "holder_length_mm": {"type": "number", "description": "Holder length (mm, default 50)"},
                "stock_bounds": {
                    "type": "object",
                    "description": "Stock AABB: {x_min,x_max,y_min,y_max,z_min,z_max}",
                    "properties": {
                        "x_min": {"type": "number"},
                        "x_max": {"type": "number"},
                        "y_min": {"type": "number"},
                        "y_max": {"type": "number"},
                        "z_min": {"type": "number"},
                        "z_max": {"type": "number"},
                    },
                },
                "table_pivot_z": {
                    "type": "number",
                    "description": "Z level of rotary table pivot point (mm, default 0)",
                },
            },
            "required": ["toolpath_points"],
        },
    )

_build_spec()


async def run_cam_machine_collision_check(ctx, args: bytes) -> str:
    try:
        from kerf_cam._compat import err_payload, ok_payload
    except ImportError:
        try:
            from kerf_chat.tools.registry import err_payload, ok_payload
        except ImportError:
            return json.dumps({"error": "compat module not found", "code": "INTERNAL"})

    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    points = a.get("toolpath_points")
    if not points:
        return err_payload("toolpath_points is required", "BAD_ARGS")

    result = check_collisions(
        toolpath_points=points,
        tool_diameter_mm=float(a.get("tool_diameter_mm", 12.0)),
        tool_length_mm=float(a.get("tool_length_mm", 80.0)),
        holder_diameter_mm=float(a.get("holder_diameter_mm", 32.0)),
        holder_length_mm=float(a.get("holder_length_mm", 50.0)),
        stock_bounds=a.get("stock_bounds"),
        table_pivot_z=float(a.get("table_pivot_z", 0.0)),
    )

    return ok_payload(result)
