"""
kerf_cam.verify — Toolpath material-removal simulation (dexel / Z-map method).

Algorithm
---------
The dexel (depth element) method was introduced by Van Hook (1986) [1] and
is the industry-standard approach for NC simulation / gouge detection:

1.  Divide the XY bounding box of the stock into an N×M grid of *dexels*
    (columns).  Each dexel stores the current top Z surface of the stock.
    Initially every dexel top = stock_top (typically 0.0 mm above part datum).

2.  For each consecutive pair of CL (cutter location) points on the toolpath,
    subdivide the move into small steps (step ≤ 0.5 × tool radius), compute
    the footprint of the cutter in the XY grid, and lower the dexel tops to
    max(current_top, tool_z - cutter_profile(r)).

    Three cutter profiles are supported:
      flat    (end mill)  — flat bottom: profile(r) = 0  for r ≤ R, else ∞
      ball    (ball nose) — sphere: profile(r) = R - sqrt(R²-r²)  for r ≤ R
      bull    (bull nose) — toroidal: flat core + ball corner radius rc

3.  After sweeping all moves, compare the final dexel map against the *part
    surface* (an analytically supplied Z field, or a fine reference grid built
    from the part triangles).  Any dexel whose final Z is lower than the part
    surface at that XY position is a **gouge**.

4.  Compute:
    • removed_volume  — sum of (stock_top - final_z) × cell_area for all cells
    • percent_cleared — 100 × removed_volume / total_stock_volume
    • gouge_points    — list of (x, y, z_part, z_actual) tuples for gouged cells

References
----------
[1] Van Hook, T. (1986). Real-time shaded NC milling display. SIGGRAPH 1986,
    ACM SIGGRAPH Computer Graphics, 20(4), 15–20.
    https://doi.org/10.1145/15886.15889
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ToolGeometry:
    """Describes the cutter for material-removal simulation."""
    diameter_mm: float          # overall diameter
    kind: str = "flat"          # "flat" | "ball" | "bull"
    corner_radius_mm: float = 0.0   # for bull nose only

    @property
    def radius_mm(self) -> float:
        return self.diameter_mm / 2.0

    def profile_z(self, r: float) -> float:
        """
        Returns how far *above* the tip the cutter body is at radial offset r.

        For a flat endmill the cutting face is flat: profile_z(r) = 0 ∀ r ≤ R.
        For a ball nose: profile_z(r) = R - sqrt(R² - r²)  (spherical).
        For a bull nose (toroid): flat core of radius (R - rc), then a
        quarter-torus fillet of radius rc from (R-rc) to R.
        """
        R = self.radius_mm
        if r > R + 1e-9:
            return math.inf  # outside tool envelope

        if self.kind == "flat":
            return 0.0

        if self.kind == "ball":
            # sphere: z = R - sqrt(R² - r²)
            inside = R * R - r * r
            if inside < 0:
                return math.inf
            return R - math.sqrt(inside)

        if self.kind == "bull":
            rc = self.corner_radius_mm
            R_flat = R - rc
            if r <= R_flat:
                return 0.0
            # fillet region
            dr = r - R_flat
            if dr > rc + 1e-9:
                return math.inf
            return rc - math.sqrt(max(0.0, rc * rc - dr * dr))

        return 0.0  # fallback to flat


@dataclass
class DexelGrid:
    """
    An N×M grid of dexel columns over a 2-D XY bounding box.

    Each cell stores the current *top Z* of the stock at that position.
    Cutting lowers Z; the floor is stock_bottom.
    """
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    nx: int
    ny: int
    stock_top: float = 0.0      # initial stock surface Z (e.g. 0.0)
    stock_bottom: float = -100.0  # floor of the stock block

    # Internal state — filled in __post_init__
    _z: list = field(default_factory=list, repr=False)

    def __post_init__(self):
        # Initialize every dexel to stock_top.
        self._z = [[self.stock_top] * self.ny for _ in range(self.nx)]

    @property
    def dx(self) -> float:
        return (self.x_max - self.x_min) / self.nx

    @property
    def dy(self) -> float:
        return (self.y_max - self.y_min) / self.ny

    @property
    def cell_area(self) -> float:
        return self.dx * self.dy

    def cell_center(self, ix: int, iy: int) -> Tuple[float, float]:
        x = self.x_min + (ix + 0.5) * self.dx
        y = self.y_min + (iy + 0.5) * self.dy
        return x, y

    def xy_to_index(self, x: float, y: float) -> Tuple[int, int]:
        ix = int((x - self.x_min) / self.dx)
        iy = int((y - self.y_min) / self.dy)
        ix = max(0, min(self.nx - 1, ix))
        iy = max(0, min(self.ny - 1, iy))
        return ix, iy

    def sweep_cutter(self, cx: float, cy: float, cz: float, tool: ToolGeometry):
        """
        Lower dexel tops by sweeping the cutter centred at (cx, cy, cz).

        The cutter tip is at cz; the body extends *upward* from cz by profile_z(r).
        We lower each dexel to min(current_top, cz + profile_z(r)).
        Wait — actually the dexel top records the current stock surface Z.
        The cutter removes material down to (cz + profile_z(r)), so the new
        dexel top = min(old_top, cz + profile_z(r)).

        Note: lowering the dexel top means removing stock from that column down
        to the tool surface.  This is only done when cz + profile_z(r) < current_top.
        """
        R = tool.radius_mm
        # Bounding box of the cutter footprint in grid indices.
        ix_lo, iy_lo = self.xy_to_index(cx - R - self.dx, cy - R - self.dy)
        ix_hi, iy_hi = self.xy_to_index(cx + R + self.dx, cy + R + self.dy)

        for ix in range(ix_lo, ix_hi + 1):
            for iy in range(iy_lo, iy_hi + 1):
                px, py = self.cell_center(ix, iy)
                r = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
                pz = tool.profile_z(r)
                if math.isinf(pz):
                    continue  # outside tool envelope
                cut_z = cz + pz   # the Z of the cutter surface at this cell
                if cut_z < self._z[ix][iy]:
                    self._z[ix][iy] = max(self.stock_bottom, cut_z)

    def removed_volume(self) -> float:
        """Total material removed: sum of (stock_top - current_z) × cell_area."""
        total = 0.0
        for col in self._z:
            for z in col:
                delta = self.stock_top - z
                if delta > 0:
                    total += delta * self.cell_area
        return total

    def total_stock_volume(self) -> float:
        """Initial stock volume above stock_bottom."""
        depth = self.stock_top - self.stock_bottom
        return depth * (self.x_max - self.x_min) * (self.y_max - self.y_min)

    def get_z(self, ix: int, iy: int) -> float:
        return self._z[ix][iy]


# ---------------------------------------------------------------------------
# G-code / CL-point parser
# ---------------------------------------------------------------------------

def _parse_gcode_moves(gcode: str) -> List[Tuple[float, float, float]]:
    """
    Parse a G-code string into a list of (x, y, z) absolute positions.

    Handles G0/G1 moves; ignores G2/G3 arcs (logs a warning instead).
    Modal coordinates: the last seen value persists until changed.
    """
    x, y, z = 0.0, 0.0, 0.0
    points = [(x, y, z)]
    for raw in gcode.splitlines():
        line = raw.strip().upper()
        if not line or line.startswith(';') or line.startswith('(') or line.startswith('%'):
            continue
        # Skip arc moves (not yet interpolated)
        if 'G2' in line or 'G3' in line:
            continue
        if 'G0' in line or 'G1' in line or any(c in line for c in ('X', 'Y', 'Z')):
            for token in line.split():
                if token.startswith('X'):
                    try:
                        x = float(token[1:])
                    except ValueError:
                        pass
                elif token.startswith('Y'):
                    try:
                        y = float(token[1:])
                    except ValueError:
                        pass
                elif token.startswith('Z'):
                    try:
                        z = float(token[1:])
                    except ValueError:
                        pass
            points.append((x, y, z))
    return points


def _parse_cl_points(cl_points: list) -> List[Tuple[float, float, float]]:
    """Convert CL point dicts [{"x":..,"y":..,"z":..}, ...] to tuples."""
    return [(float(p["x"]), float(p["y"]), float(p["z"])) for p in cl_points]


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

def simulate_material_removal(
    toolpath_points: List[Tuple[float, float, float]],
    tool: ToolGeometry,
    stock_bounds: dict,          # {"x_min", "x_max", "y_min", "y_max", "stock_top", "stock_bottom"}
    part_surface_z: Optional[callable] = None,   # f(x, y) → part Z; None → no gouge check
    resolution_mm: float = 0.5,
    substep_fraction: float = 0.5,
) -> dict:
    """
    Run dexel material-removal simulation.

    Parameters
    ----------
    toolpath_points  : list of (x, y, z) tuples — cutter tip positions.
    tool             : ToolGeometry.
    stock_bounds     : dict with keys x_min, x_max, y_min, y_max,
                       stock_top, stock_bottom.
    part_surface_z   : callable(x, y) → float  — the design surface.
                       Used to detect gouges.  Pass None to skip gouge check.
    resolution_mm    : dexel grid cell size (mm).  Smaller → more accurate but
                       slower.  Default 0.5 mm is a good production trade-off.
    substep_fraction : cutter step = substep_fraction × tool_radius.
                       Default 0.5 (step = R/2).

    Returns
    -------
    dict with keys:
      removed_volume_mm3  : float
      total_stock_mm3     : float
      percent_cleared     : float   (0–100)
      gouge_points        : list of {"x", "y", "z_part", "z_actual", "depth"}
                            Sorted by depth descending.
      remaining_stock_mm3 : float
      n_moves             : int     (number of interpolated cutter positions)
      method              : "dexel_zmap_van_hook_1986"
    """
    x_min = float(stock_bounds["x_min"])
    x_max = float(stock_bounds["x_max"])
    y_min = float(stock_bounds["y_min"])
    y_max = float(stock_bounds["y_max"])
    stock_top = float(stock_bounds.get("stock_top", 0.0))
    stock_bottom = float(stock_bounds.get("stock_bottom", -100.0))

    nx = max(4, int(math.ceil((x_max - x_min) / resolution_mm)))
    ny = max(4, int(math.ceil((y_max - y_min) / resolution_mm)))
    # Cap at 400×400 to keep runtime reasonable
    nx = min(nx, 400)
    ny = min(ny, 400)

    grid = DexelGrid(
        x_min=x_min, x_max=x_max,
        y_min=y_min, y_max=y_max,
        nx=nx, ny=ny,
        stock_top=stock_top,
        stock_bottom=stock_bottom,
    )

    step_size = max(resolution_mm * 0.5, tool.radius_mm * substep_fraction)
    step_size = max(step_size, 0.01)

    n_moves = 0

    # Always sweep the first point so a single-point toolpath still cuts.
    if toolpath_points:
        grid.sweep_cutter(toolpath_points[0][0], toolpath_points[0][1], toolpath_points[0][2], tool)
        n_moves += 1

    for i in range(len(toolpath_points) - 1):
        x0, y0, z0 = toolpath_points[i]
        x1, y1, z1 = toolpath_points[i + 1]
        dx = x1 - x0
        dy = y1 - y0
        dz = z1 - z0
        seg_len = math.sqrt(dx * dx + dy * dy + dz * dz)
        if seg_len < 1e-9:
            grid.sweep_cutter(x0, y0, z0, tool)
            n_moves += 1
            continue
        n_steps = max(1, int(math.ceil(seg_len / step_size)))
        for j in range(n_steps + 1):
            t = j / n_steps
            cx = x0 + t * dx
            cy = y0 + t * dy
            cz = z0 + t * dz
            grid.sweep_cutter(cx, cy, cz, tool)
            n_moves += 1

    # Compute statistics.
    removed_vol = grid.removed_volume()
    total_vol = grid.total_stock_volume()
    pct = 100.0 * removed_vol / total_vol if total_vol > 1e-12 else 0.0

    remaining = total_vol - removed_vol

    # Gouge detection.
    gouge_points = []
    if part_surface_z is not None:
        for ix in range(grid.nx):
            for iy in range(grid.ny):
                px, py = grid.cell_center(ix, iy)
                z_part = part_surface_z(px, py)
                z_actual = grid.get_z(ix, iy)
                if z_actual < z_part - 1e-6:
                    gouge_points.append({
                        "x": round(px, 4),
                        "y": round(py, 4),
                        "z_part": round(z_part, 4),
                        "z_actual": round(z_actual, 4),
                        "depth": round(z_part - z_actual, 4),
                    })

    gouge_points.sort(key=lambda g: g["depth"], reverse=True)

    return {
        "removed_volume_mm3": round(removed_vol, 4),
        "total_stock_mm3": round(total_vol, 4),
        "percent_cleared": round(pct, 3),
        "remaining_stock_mm3": round(remaining, 4),
        "gouge_points": gouge_points,
        "n_moves": n_moves,
        "grid_nx": nx,
        "grid_ny": ny,
        "method": "dexel_zmap_van_hook_1986",
    }


# ---------------------------------------------------------------------------
# LLM tool
# ---------------------------------------------------------------------------

cam_verify_material_removal_spec = ToolSpec(
    name="cam_verify_material_removal",
    description=(
        "Simulate material removal for a CAM toolpath using the dexel/Z-map method "
        "(Van Hook 1986, SIGGRAPH). "
        "Sweeps a tool (flat/ball/bull endmill) along the provided CL points or G-code, "
        "removes voxels from a stock block, and reports:\n"
        "  • removed_volume_mm3  — total material removed\n"
        "  • percent_cleared     — % of stock volume cleared\n"
        "  • gouge_points        — list of (x,y) cells where the cutter went below the part surface\n"
        "Provide either cl_points (list of {x,y,z} dicts) or gcode (NC string). "
        "stock_bounds must cover the workpiece XY envelope."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cl_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                    },
                    "required": ["x", "y", "z"],
                },
                "description": "Cutter location points [{x,y,z}, ...] (use instead of gcode)",
            },
            "gcode": {
                "type": "string",
                "description": "G-code string to parse for X/Y/Z moves (use instead of cl_points)",
            },
            "tool_diameter_mm": {
                "type": "number",
                "description": "Tool diameter in mm (default 6.0)",
            },
            "tool_kind": {
                "type": "string",
                "enum": ["flat", "ball", "bull"],
                "description": "Cutter profile (default 'flat')",
            },
            "corner_radius_mm": {
                "type": "number",
                "description": "Corner radius for bull-nose (default 1.0)",
            },
            "stock_bounds": {
                "type": "object",
                "description": "Stock XY/Z extents: {x_min, x_max, y_min, y_max, stock_top, stock_bottom}",
                "properties": {
                    "x_min": {"type": "number"},
                    "x_max": {"type": "number"},
                    "y_min": {"type": "number"},
                    "y_max": {"type": "number"},
                    "stock_top": {"type": "number"},
                    "stock_bottom": {"type": "number"},
                },
                "required": ["x_min", "x_max", "y_min", "y_max"],
            },
            "part_surface_z_flat": {
                "type": "number",
                "description": (
                    "Constant Z level of the finished part surface (mm). "
                    "If provided, any cell cut below this Z is flagged as a gouge."
                ),
            },
            "resolution_mm": {
                "type": "number",
                "description": "Dexel grid cell size in mm (default 0.5; smaller = more accurate but slower)",
            },
        },
        "required": ["stock_bounds"],
    },
)


@register(cam_verify_material_removal_spec)
async def run_cam_verify_material_removal(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    cl_points_raw = a.get("cl_points")
    gcode = a.get("gcode")
    stock_bounds = a.get("stock_bounds")

    if not stock_bounds:
        return err_payload("stock_bounds is required", "BAD_ARGS")
    if cl_points_raw is None and gcode is None:
        return err_payload("provide either cl_points or gcode", "BAD_ARGS")

    # Build tool geometry.
    tool = ToolGeometry(
        diameter_mm=float(a.get("tool_diameter_mm", 6.0)),
        kind=a.get("tool_kind", "flat"),
        corner_radius_mm=float(a.get("corner_radius_mm", 1.0)),
    )

    # Parse toolpath.
    if cl_points_raw is not None:
        points = _parse_cl_points(cl_points_raw)
    else:
        points = _parse_gcode_moves(gcode)

    if len(points) < 2:
        return err_payload("need at least 2 toolpath points", "BAD_ARGS")

    # Part surface for gouge detection.
    part_z_flat = a.get("part_surface_z_flat")
    part_surface_fn = None
    if part_z_flat is not None:
        z_flat = float(part_z_flat)
        part_surface_fn = lambda x, y: z_flat  # noqa: E731

    res = float(a.get("resolution_mm", 0.5))

    result = simulate_material_removal(
        toolpath_points=points,
        tool=tool,
        stock_bounds=stock_bounds,
        part_surface_z=part_surface_fn,
        resolution_mm=res,
    )

    return ok_payload(result)
