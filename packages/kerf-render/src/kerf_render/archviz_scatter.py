"""
archviz_scatter.py — Procedural scatter / population engine for Kerf archviz.

Distributes asset instances across a rectangular surface area with:
  * Poisson-disk sampling  (method="poisson")   — respects min_spacing hard radius
  * Jittered-grid sampling (method="grid")       — regular grid + random offset
  * Density control        — instances per m²
  * Random seed            — deterministic output
  * Scale / rotation jitter
  * Slope mask             — filter by surface normal angle (needs height_field)
  * Altitude mask          — filter by Z range
  * Exclusion zones        — axis-aligned rectangles (no instances placed inside)
  * Collision-avoidance    — min_spacing enforced on each instance centre

Output: list of InstanceTransform dicts
  {
    "id":        int,            # sequential index
    "asset_id":  str,            # references archviz_assets catalogue
    "position":  [x, y, z],
    "rotation":  [rx, ry, rz],   # Euler XYZ in degrees
    "scale":     [sx, sy, sz],
  }
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

# ── Public constants ───────────────────────────────────────────────────────
DEFAULT_MIN_SPACING = 0.5   # metres
DEFAULT_MAX_DENSITY = 50.0  # instances / m²  (safety cap)
POISSON_MAX_ATTEMPTS = 30   # Bridson algorithm rejection attempts per active sample


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class ScatterArea:
    """Axis-aligned bounding rectangle for the scatter surface."""
    x_min: float = 0.0
    y_min: float = 0.0
    x_max: float = 10.0
    y_max: float = 10.0
    base_z: float = 0.0


@dataclass
class HeightField:
    """Optional 2-D height field for slope / altitude masking.

    ``grid`` is a list of rows (row = list of floats).  Size is (rows × cols).
    The field covers the same [x_min, x_max] × [y_min, y_max] as the ScatterArea.
    """
    grid: list[list[float]] = field(default_factory=list)
    rows: int = 0
    cols: int = 0
    x_min: float = 0.0
    y_min: float = 0.0
    x_max: float = 10.0
    y_max: float = 10.0

    def sample_z(self, x: float, y: float) -> float:
        """Bilinear interpolation of height at (x, y)."""
        if self.rows == 0 or self.cols == 0:
            return 0.0
        tx = (x - self.x_min) / max(self.x_max - self.x_min, 1e-9)
        ty = (y - self.y_min) / max(self.y_max - self.y_min, 1e-9)
        tx = max(0.0, min(1.0, tx))
        ty = max(0.0, min(1.0, ty))
        cx = tx * (self.cols - 1)
        cy = ty * (self.rows - 1)
        ix = int(cx); ix = min(ix, self.cols - 2)
        iy = int(cy); iy = min(iy, self.rows - 2)
        fx = cx - ix
        fy = cy - iy
        z00 = self.grid[iy][ix]
        z10 = self.grid[iy][ix + 1]
        z01 = self.grid[iy + 1][ix]
        z11 = self.grid[iy + 1][ix + 1]
        return (z00 * (1 - fx) * (1 - fy)
                + z10 * fx * (1 - fy)
                + z01 * (1 - fx) * fy
                + z11 * fx * fy)

    def slope_deg(self, x: float, y: float) -> float:
        """Approximate slope in degrees at (x, y) via central differences."""
        if self.rows < 2 or self.cols < 2:
            return 0.0
        dx = (self.x_max - self.x_min) / max(self.cols - 1, 1)
        dy = (self.y_max - self.y_min) / max(self.rows - 1, 1)
        dzdx = (self.sample_z(x + dx, y) - self.sample_z(x - dx, y)) / (2 * dx) if dx else 0.0
        dzdy = (self.sample_z(x, y + dy) - self.sample_z(x, y - dy)) / (2 * dy) if dy else 0.0
        slope_rad = math.atan(math.sqrt(dzdx ** 2 + dzdy ** 2))
        return math.degrees(slope_rad)


@dataclass
class ExclusionZone:
    """Axis-aligned rectangle within which no instances are placed."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float


# ── Internal helpers ──────────────────────────────────────────────────────

def _point_in_exclusion(x: float, y: float, zones: list[ExclusionZone]) -> bool:
    for z in zones:
        if z.x_min <= x <= z.x_max and z.y_min <= y <= z.y_max:
            return True
    return False


def _too_close(
    x: float, y: float,
    placed: list[dict],
    min_spacing: float,
) -> bool:
    r2 = min_spacing ** 2
    for p in placed:
        px, py = p["position"][0], p["position"][1]
        if (x - px) ** 2 + (y - py) ** 2 < r2:
            return True
    return False


# ── Poisson-disk sampling (Bridson 2007) ─────────────────────────────────

def _poisson_disk(
    rng: random.Random,
    x_min: float, y_min: float,
    x_max: float, y_max: float,
    min_spacing: float,
    max_count: int,
    max_attempts: int = POISSON_MAX_ATTEMPTS,
) -> list[tuple[float, float]]:
    """Return Poisson-disk sampled (x, y) points inside the bounding rectangle."""
    w = x_max - x_min
    h = y_max - y_min
    if w <= 0 or h <= 0:
        return []

    cell = min_spacing / math.sqrt(2.0)
    grid_cols = max(1, int(math.ceil(w / cell)))
    grid_rows = max(1, int(math.ceil(h / cell)))
    grid: dict[tuple[int, int], tuple[float, float]] = {}

    def _grid_key(x: float, y: float) -> tuple[int, int]:
        return int((x - x_min) / cell), int((y - y_min) / cell)

    def _too_close_grid(x: float, y: float) -> bool:
        gx, gy = _grid_key(x, y)
        for nx in range(max(0, gx - 2), min(grid_cols, gx + 3)):
            for ny in range(max(0, gy - 2), min(grid_rows, gy + 3)):
                if (nx, ny) in grid:
                    px, py = grid[(nx, ny)]
                    if (x - px) ** 2 + (y - py) ** 2 < min_spacing ** 2:
                        return True
        return False

    # Seed with a first random point
    sx = rng.uniform(x_min, x_max)
    sy = rng.uniform(y_min, y_max)
    pts: list[tuple[float, float]] = [(sx, sy)]
    grid[_grid_key(sx, sy)] = (sx, sy)
    active = [0]

    while active and len(pts) < max_count:
        idx = rng.randrange(len(active))
        ax, ay = pts[active[idx]]
        placed_new = False
        for _ in range(max_attempts):
            # Random point in annulus [r, 2r]
            angle = rng.uniform(0, 2 * math.pi)
            radius = rng.uniform(min_spacing, 2 * min_spacing)
            nx = ax + radius * math.cos(angle)
            ny = ay + radius * math.sin(angle)
            if not (x_min <= nx <= x_max and y_min <= ny <= y_max):
                continue
            if _too_close_grid(nx, ny):
                continue
            pts.append((nx, ny))
            grid[_grid_key(nx, ny)] = (nx, ny)
            active.append(len(pts) - 1)
            placed_new = True
            if len(pts) >= max_count:
                break
        if not placed_new:
            active.pop(idx)

    return pts


# ── Jittered-grid sampling ────────────────────────────────────────────────

def _jittered_grid(
    rng: random.Random,
    x_min: float, y_min: float,
    x_max: float, y_max: float,
    density: float,
) -> list[tuple[float, float]]:
    """Regular grid with a jitter of up to half a cell-width in each axis."""
    w = x_max - x_min
    h = y_max - y_min
    if w <= 0 or h <= 0:
        return []
    total = density * w * h
    n_cols = max(1, int(math.sqrt(total * w / h)))
    n_rows = max(1, int(total / n_cols))
    cx = w / n_cols
    cy = h / n_rows
    pts = []
    for row in range(n_rows):
        for col in range(n_cols):
            jx = rng.uniform(-0.5 * cx, 0.5 * cx)
            jy = rng.uniform(-0.5 * cy, 0.5 * cy)
            x = x_min + (col + 0.5) * cx + jx
            y = y_min + (row + 0.5) * cy + jy
            x = max(x_min, min(x_max, x))
            y = max(y_min, min(y_max, y))
            pts.append((x, y))
    return pts


# ── Public API ────────────────────────────────────────────────────────────

def scatter(
    area: dict[str, Any],
    asset_ids: list[str],
    density: float = 1.0,
    seed: int = 0,
    min_spacing: float = DEFAULT_MIN_SPACING,
    scale_jitter: float = 0.2,
    rotation_jitter_deg: float = 360.0,
    method: str = "poisson",
    exclusion_zones: list[dict[str, Any]] | None = None,
    height_field: dict[str, Any] | None = None,
    max_slope_deg: float | None = None,
    altitude_min: float | None = None,
    altitude_max: float | None = None,
) -> list[dict[str, Any]]:
    """Scatter *asset_ids* over *area*, returning a list of instance transforms.

    Parameters
    ----------
    area : dict with keys x_min, y_min, x_max, y_max, [base_z]
    asset_ids : list of asset IDs from the archviz catalogue; instances cycle
        through this list in random order.
    density : instances per m²
    seed : random seed for reproducibility
    min_spacing : minimum centre-to-centre distance in metres (Poisson hard-radius)
    scale_jitter : ±fractional scale jitter (0 = no jitter, 1 = ±100 %)
    rotation_jitter_deg : random rotation range around Z axis (0–360)
    method : "poisson" | "grid"
    exclusion_zones : list of dicts {x_min, y_min, x_max, y_max}
    height_field : dict {grid:[[...]], rows, cols, x_min, y_min, x_max, y_max}
    max_slope_deg : discard instances steeper than this angle
    altitude_min/max : discard instances outside this Z range
    """
    density = max(0.0, min(float(density), DEFAULT_MAX_DENSITY))
    if density == 0.0:
        return []
    rng = random.Random(seed)

    sa = ScatterArea(
        x_min=float(area.get("x_min", 0)),
        y_min=float(area.get("y_min", 0)),
        x_max=float(area.get("x_max", 10)),
        y_max=float(area.get("y_max", 10)),
        base_z=float(area.get("base_z", 0)),
    )

    excl_zones: list[ExclusionZone] = []
    for ez in (exclusion_zones or []):
        excl_zones.append(ExclusionZone(
            x_min=float(ez.get("x_min", 0)),
            y_min=float(ez.get("y_min", 0)),
            x_max=float(ez.get("x_max", 0)),
            y_max=float(ez.get("y_max", 0)),
        ))

    hf: HeightField | None = None
    if height_field and height_field.get("grid"):
        hf = HeightField(
            grid=height_field["grid"],
            rows=int(height_field.get("rows", len(height_field["grid"]))),
            cols=int(height_field.get("cols", len(height_field["grid"][0]) if height_field["grid"] else 0)),
            x_min=float(height_field.get("x_min", sa.x_min)),
            y_min=float(height_field.get("y_min", sa.y_min)),
            x_max=float(height_field.get("x_max", sa.x_max)),
            y_max=float(height_field.get("y_max", sa.y_max)),
        )

    w = sa.x_max - sa.x_min
    h = sa.y_max - sa.y_min
    total_area = max(w * h, 0.0)
    max_count = int(density * total_area) + 1

    # Generate candidate positions
    if method == "grid":
        candidates = _jittered_grid(rng, sa.x_min, sa.y_min, sa.x_max, sa.y_max, density)
    else:
        candidates = _poisson_disk(
            rng, sa.x_min, sa.y_min, sa.x_max, sa.y_max,
            min_spacing=max(min_spacing, 1e-3),
            max_count=max(1, max_count),
        )

    if not asset_ids:
        return []

    instances: list[dict[str, Any]] = []
    asset_pool = list(asset_ids)
    rng.shuffle(asset_pool)

    for i, (cx, cy) in enumerate(candidates):
        # Exclusion zone test
        if _point_in_exclusion(cx, cy, excl_zones):
            continue

        # Height field tests
        z = sa.base_z
        if hf is not None:
            z = hf.sample_z(cx, cy) + sa.base_z
            if max_slope_deg is not None:
                slope = hf.slope_deg(cx, cy)
                if slope > max_slope_deg:
                    continue
        if altitude_min is not None and z < altitude_min:
            continue
        if altitude_max is not None and z > altitude_max:
            continue

        # Collision-avoidance (for jittered-grid, which doesn't guarantee spacing)
        if method == "grid" and _too_close(cx, cy, instances, min_spacing):
            continue

        # Assign asset (cycle round-robin with some shuffle per instance)
        asset_id = asset_pool[i % len(asset_pool)]

        # Rotation jitter around Z
        rz = rng.uniform(-rotation_jitter_deg / 2, rotation_jitter_deg / 2)

        # Scale jitter
        base = 1.0
        sj = rng.uniform(-scale_jitter, scale_jitter)
        s = max(0.1, base + sj)

        instances.append({
            "id":       len(instances),
            "asset_id": asset_id,
            "position": [round(cx, 4), round(cy, 4), round(z, 4)],
            "rotation": [0.0, 0.0, round(rz, 3)],
            "scale":    [round(s, 4), round(s, 4), round(s, 4)],
        })

    return instances
