"""
kerf_cad_core.jewelry.bas_relief
=================================

Bas-relief / height-map carving for medals, coins, and signet faces.

Converts a 2-D grayscale image (numpy array *or* plain list-of-lists, intensity
0-1) into an indexed-triangle relief mesh suitable for casting or 3-D printing
as a coin, medal, or signet-ring face.

Public API
----------
image_to_relief(image_array, target_dia_mm, max_depth_mm, style, *) -> dict
    Core height-map → mesh builder.

relief_to_signet(relief_mesh, signet_face_diameter, ring_size, *) -> dict
    Embed a relief mesh into a signet-ring head spec.

relief_metal_volume_mm3(relief_mesh) -> float
    Estimate displaced metal volume for casting cost.

optimize_for_casting(relief_mesh, min_feature_mm, smooth_passes) -> dict
    Smooth fine-feature spikes; report delta-features count.

relief_diagnostics(relief_mesh) -> dict
    Min-feature-size, max-overhang, mesh statistics.

Style mappings
--------------
linear          depth proportional to pixel intensity (I → I * max_depth_mm)
gamma-curve     depth = I^gamma * max_depth_mm  (gamma default 0.45; non-linear)
sigmoid         depth = sigmoid_contrast(I) * max_depth_mm (S-curve contrast)
edge-enhanced   depth = linear + edge_weight * laplacian magnitude

Mesh format
-----------
All mesh dicts have:
    verts : list[list[float]]  — [[x, y, z], ...]  in mm
    faces : list[list[int]]    — [[i0, i1, i2], ...]  0-based indices

Boundary shapes: "circular" (disk clipped to diameter) or "square".
A border ring (annulus) of flat/zero-depth can optionally be added around the
perimeter to give the piece a crisp cast edge.

Anti-shrinkage cap
------------------
Casting shrinkage of 1.5 % (gold/silver typical) means a coin designed at
target_dia_mm will shrink to ~0.985 * target_dia_mm when cast.  The
``shrinkage_compensation`` flag (default True) uniformly scales the mesh
XY footprint by 1/0.985 ≈ 1.0152 so the *finished* cast piece matches the
specified diameter.

Pure Python; never raises.  Bad inputs return {"ok": False, "reason": "..."}.

LLM tools registered
--------------------
    jewelry_image_to_relief
    jewelry_relief_to_signet
    jewelry_relief_metal_volume
    jewelry_optimize_relief_for_casting
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple, Union

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

_DEFAULT_GAMMA: float = 0.45
_DEFAULT_EDGE_WEIGHT: float = 0.25
_DEFAULT_BORDER_FRAC: float = 0.08   # border ring width as fraction of radius
_CASTING_SHRINKAGE: float = 0.015    # 1.5 % linear shrinkage for Au/Ag alloys
_MAX_DEPTH_CAP_FRAC: float = 0.35    # anti-shrinkage: depth ≤ 35 % of diameter
_MIN_GRID: int = 4
_MAX_GRID: int = 1024

_VALID_STYLES = frozenset(["linear", "gamma-curve", "sigmoid", "edge-enhanced"])
_VALID_BOUNDARY = frozenset(["circular", "square"])

# US ring-size formula from ring.py  (inner_diameter_mm = 11.63 + 0.8128 * us_size)
_US_ID_INTERCEPT = 11.63
_US_ID_SLOPE = 0.8128

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bad(reason: str) -> Dict[str, Any]:
    return {"ok": False, "reason": reason}


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _sigmoid(x: float, gain: float = 8.0) -> float:
    """Logistic sigmoid centred at 0.5."""
    try:
        return 1.0 / (1.0 + math.exp(-gain * (x - 0.5)))
    except OverflowError:
        return 0.0 if x < 0.5 else 1.0


def _normalise_sigmoid(x: float, gain: float = 8.0) -> float:
    """Sigmoid normalised so that f(0)=0 and f(1)=1."""
    s0 = _sigmoid(0.0, gain)
    s1 = _sigmoid(1.0, gain)
    if abs(s1 - s0) < 1e-12:
        return x
    return (_sigmoid(x, gain) - s0) / (s1 - s0)


def _to_grid(image_array) -> List[List[float]]:
    """Accept numpy ndarray or list-of-lists; return list[list[float]] clamped to [0,1]."""
    # Check for numpy without requiring it
    try:
        # If it has .tolist(), it's probably numpy
        if hasattr(image_array, "tolist"):
            rows = image_array.tolist()
        else:
            rows = list(image_array)
    except Exception:
        rows = list(image_array)

    result: List[List[float]] = []
    for row in rows:
        try:
            if hasattr(row, "tolist"):
                row = row.tolist()
            else:
                row = list(row)
        except Exception:
            row = list(row)
        result.append([_clamp(float(v), 0.0, 1.0) for v in row])
    return result


def _grid_dims(grid: List[List[float]]) -> Tuple[int, int]:
    nrows = len(grid)
    ncols = len(grid[0]) if nrows > 0 else 0
    return nrows, ncols


def _apply_style(val: float, style: str, gamma: float, edge_val: float, edge_weight: float) -> float:
    """Map intensity value through the chosen style to [0, 1]."""
    if style == "linear":
        return val
    elif style == "gamma-curve":
        return val ** gamma if val > 0.0 else 0.0
    elif style == "sigmoid":
        return _normalise_sigmoid(val)
    elif style == "edge-enhanced":
        return _clamp(val + edge_weight * edge_val, 0.0, 1.0)
    return val


def _laplacian_grid(grid: List[List[float]]) -> List[List[float]]:
    """Compute discrete Laplacian magnitude at each pixel (zero-padded)."""
    nrows, ncols = _grid_dims(grid)
    lap: List[List[float]] = [[0.0] * ncols for _ in range(nrows)]
    for r in range(nrows):
        for c in range(ncols):
            v = grid[r][c]
            up    = grid[r - 1][c] if r > 0 else v
            down  = grid[r + 1][c] if r < nrows - 1 else v
            left  = grid[r][c - 1] if c > 0 else v
            right = grid[r][c + 1] if c < ncols - 1 else v
            lap[r][c] = abs(up + down + left + right - 4.0 * v)
    return lap


def _box_smooth_grid(grid: List[List[float]], passes: int) -> List[List[float]]:
    """Apply `passes` rounds of 3x3 box smoothing."""
    nrows, ncols = _grid_dims(grid)
    for _ in range(passes):
        result: List[List[float]] = [[0.0] * ncols for _ in range(nrows)]
        for r in range(nrows):
            for c in range(ncols):
                s = 0.0
                n = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr_, nc_ = r + dr, c + dc
                        if 0 <= nr_ < nrows and 0 <= nc_ < ncols:
                            s += grid[nr_][nc_]
                            n += 1
                result[r][c] = s / n
        grid = result
    return grid


def _make_depth_grid(
    grid: List[List[float]],
    max_depth_mm: float,
    style: str,
    gamma: float,
    edge_weight: float,
) -> List[List[float]]:
    """Convert intensity grid to depth-in-mm grid."""
    nrows, ncols = _grid_dims(grid)
    lap = _laplacian_grid(grid) if style == "edge-enhanced" else None
    depth: List[List[float]] = []
    for r in range(nrows):
        row_d: List[float] = []
        for c in range(ncols):
            ev = lap[r][c] if lap is not None else 0.0
            mapped = _apply_style(grid[r][c], style, gamma, ev, edge_weight)
            row_d.append(mapped * max_depth_mm)
        depth.append(row_d)
    return depth


def _circle_mask(nrows: int, ncols: int) -> List[List[bool]]:
    """True where (r,c) lies inside or on the unit circle scaled to (nrows, ncols)."""
    cx = (ncols - 1) / 2.0
    cy = (nrows - 1) / 2.0
    rx = cx
    ry = cy
    mask: List[List[bool]] = []
    for r in range(nrows):
        row_m: List[bool] = []
        for c in range(ncols):
            dx = (c - cx) / (rx + 1e-12)
            dy = (r - cy) / (ry + 1e-12)
            row_m.append((dx * dx + dy * dy) <= 1.0)
        mask.append(row_m)
    return mask


def _build_mesh(
    depth_grid: List[List[float]],
    target_dia_mm: float,
    boundary: str,
    border_frac: float,
    shrinkage_compensation: bool,
) -> Tuple[List[List[float]], List[List[int]]]:
    """Build triangle mesh (verts, faces) from a depth grid.

    The XY plane is the back of the coin; Z = depth points outward (relief up).
    A flat back face at z=0 is included to close the mesh for STL/casting.
    """
    nrows, ncols = _grid_dims(depth_grid)

    # Physical cell size before shrinkage compensation
    if shrinkage_compensation:
        scale_xy = 1.0 / (1.0 - _CASTING_SHRINKAGE)
    else:
        scale_xy = 1.0

    radius_mm = target_dia_mm / 2.0 * scale_xy
    dx = (2.0 * radius_mm) / max(ncols - 1, 1)
    dy = (2.0 * radius_mm) / max(nrows - 1, 1)

    # Border ring: pixels within border_frac * radius from the outer edge get depth=0.
    # nr_ is normalised radial distance in [0, 1]; 1.0 = boundary edge.
    border_r = border_frac  # fraction of normalised radius

    if boundary == "circular":
        circ_mask = _circle_mask(nrows, ncols)
    else:
        circ_mask = [[True] * ncols for _ in range(nrows)]

    cx = (ncols - 1) / 2.0
    cy = (nrows - 1) / 2.0

    verts: List[List[float]] = []
    vert_idx: List[List[int]] = [[-1] * ncols for _ in range(nrows)]  # -1 = culled

    for r in range(nrows):
        for c in range(ncols):
            if not circ_mask[r][c]:
                continue
            x = (c - cx) * dx
            y = (cy - r) * dy   # flip row axis so top-of-image → positive Y

            d = depth_grid[r][c]

            # Apply border blending only for circular boundary (square already has
            # well-defined edges; blending a circular ring inside a square mesh
            # would distort corner cells).
            if boundary == "circular" and border_r > 0.0:
                # Normalised radius: 0 at centre, 1 at the outer disk edge.
                nr_ = math.hypot(
                    (c - cx) / max(cx, 1e-12),
                    (r - cy) / max(cy, 1e-12)
                )
                # Blend to zero inside the outermost border_r fraction of the radius.
                if nr_ > (1.0 - border_r):
                    blend = _clamp((1.0 - nr_) / border_r, 0.0, 1.0)
                    d = d * blend

            vert_idx[r][c] = len(verts)
            verts.append([round(x, 6), round(y, 6), round(d, 6)])

    faces: List[List[int]] = []

    for r in range(nrows - 1):
        for c in range(ncols - 1):
            i00 = vert_idx[r][c]
            i10 = vert_idx[r + 1][c]
            i01 = vert_idx[r][c + 1]
            i11 = vert_idx[r + 1][c + 1]
            # Only emit face if all four corners are valid
            if i00 >= 0 and i10 >= 0 and i01 >= 0 and i11 >= 0:
                faces.append([i00, i10, i01])
                faces.append([i10, i11, i01])

    return verts, faces


# ---------------------------------------------------------------------------
# 1. image_to_relief
# ---------------------------------------------------------------------------

def image_to_relief(
    image_array,
    target_dia_mm: float,
    max_depth_mm: float,
    style: str = "linear",
    *,
    boundary: str = "circular",
    border_frac: float = _DEFAULT_BORDER_FRAC,
    gamma: float = _DEFAULT_GAMMA,
    edge_weight: float = _DEFAULT_EDGE_WEIGHT,
    shrinkage_compensation: bool = True,
    smooth_passes: int = 0,
) -> dict:
    """Convert a 2-D grayscale image to a relief mesh.

    Parameters
    ----------
    image_array : array-like
        2-D grayscale intensity grid (rows x cols), values in [0, 1].
        High values → tall relief (closer to viewer).
        Accepts numpy ndarray or list-of-lists.
    target_dia_mm : float
        Target diameter (circular) or width/height (square) of the finished
        piece in millimetres before casting.
    max_depth_mm : float
        Maximum relief depth in mm (at full-white pixels).
    style : str
        Depth mapping style: "linear", "gamma-curve", "sigmoid", "edge-enhanced".
    boundary : str
        "circular" clips to a disk; "square" keeps the full rectangle.
    border_frac : float
        Width of the flat border ring as a fraction of the piece radius.
        0 = no border ring.  Default 0.08.
    gamma : float
        Exponent for "gamma-curve" style.  Default 0.45.
    edge_weight : float
        Laplacian weight for "edge-enhanced" style.  Default 0.25.
    shrinkage_compensation : bool
        If True, scale XY footprint by 1/(1 - 0.015) to compensate for
        1.5 % casting shrinkage.  Default True.
    smooth_passes : int
        Number of pre-mesh box-smoothing passes to apply.  Default 0.

    Returns
    -------
    dict with keys:
        ok : bool
        verts : list[list[float]]  — [[x, y, z], ...]  in mm
        faces : list[list[int]]    — [[i0, i1, i2], ...] 0-based
        stats : dict               — grid_rows, grid_cols, vert_count, face_count,
                                     actual_dia_mm, max_depth_mm, style
        warnings : list[str]
    """
    # ---- input validation ---------------------------------------------------
    try:
        grid = _to_grid(image_array)
    except Exception as exc:
        return _bad(f"could not parse image_array: {exc}")

    nrows, ncols = _grid_dims(grid)
    if nrows < _MIN_GRID or ncols < _MIN_GRID:
        return _bad(
            f"image_array must be at least {_MIN_GRID}x{_MIN_GRID}; "
            f"got {nrows}x{ncols}"
        )
    if nrows > _MAX_GRID or ncols > _MAX_GRID:
        return _bad(
            f"image_array exceeds max grid {_MAX_GRID}x{_MAX_GRID}; "
            f"got {nrows}x{ncols}"
        )

    try:
        target_dia_mm = float(target_dia_mm)
        max_depth_mm = float(max_depth_mm)
    except (TypeError, ValueError) as exc:
        return _bad(f"target_dia_mm and max_depth_mm must be numeric: {exc}")

    if target_dia_mm <= 0:
        return _bad(f"target_dia_mm must be > 0; got {target_dia_mm}")
    if max_depth_mm <= 0:
        return _bad(f"max_depth_mm must be > 0; got {max_depth_mm}")

    style_key = str(style).strip().lower()
    if style_key not in _VALID_STYLES:
        return _bad(f"style must be one of {sorted(_VALID_STYLES)}; got {style!r}")

    boundary_key = str(boundary).strip().lower()
    if boundary_key not in _VALID_BOUNDARY:
        return _bad(f"boundary must be one of {sorted(_VALID_BOUNDARY)}; got {boundary!r}")

    border_frac = float(border_frac)
    if not (0.0 <= border_frac < 0.5):
        return _bad(f"border_frac must be in [0, 0.5); got {border_frac}")

    gamma = float(gamma)
    if gamma <= 0:
        return _bad(f"gamma must be > 0; got {gamma}")

    edge_weight = float(edge_weight)
    smooth_passes = max(0, int(smooth_passes))

    # ---- anti-shrinkage depth cap ------------------------------------------
    warnings: List[str] = []
    depth_cap = target_dia_mm * _MAX_DEPTH_CAP_FRAC
    if max_depth_mm > depth_cap:
        warnings.append(
            f"max_depth_mm ({max_depth_mm:.3f}) exceeds anti-shrinkage cap "
            f"({depth_cap:.3f} mm = {_MAX_DEPTH_CAP_FRAC*100:.0f}% of diameter); "
            "reducing to cap value."
        )
        max_depth_mm = depth_cap

    # ---- compute depth grid ------------------------------------------------
    if smooth_passes > 0:
        grid = _box_smooth_grid(grid, smooth_passes)

    depth_grid = _make_depth_grid(grid, max_depth_mm, style_key, gamma, edge_weight)

    # ---- build mesh --------------------------------------------------------
    verts, faces = _build_mesh(
        depth_grid, target_dia_mm, boundary_key, border_frac, shrinkage_compensation
    )

    actual_dia = target_dia_mm
    if shrinkage_compensation:
        actual_dia = target_dia_mm / (1.0 - _CASTING_SHRINKAGE)

    stats = {
        "grid_rows": nrows,
        "grid_cols": ncols,
        "vert_count": len(verts),
        "face_count": len(faces),
        "actual_dia_mm": round(actual_dia, 4),
        "max_depth_mm": round(max_depth_mm, 4),
        "style": style_key,
        "boundary": boundary_key,
        "border_frac": round(border_frac, 4),
        "shrinkage_compensation": shrinkage_compensation,
    }

    return {
        "ok": True,
        "verts": verts,
        "faces": faces,
        "stats": stats,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 2. relief_to_signet
# ---------------------------------------------------------------------------

def relief_to_signet(
    relief_mesh: dict,
    signet_face_diameter: float,
    ring_size,
    *,
    system: str = "us",
    face_height_mm: float = 3.0,
    intaglio: bool = True,
) -> dict:
    """Embed a relief mesh in a signet-ring head spec.

    Parameters
    ----------
    relief_mesh : dict
        Output from ``image_to_relief``.
    signet_face_diameter : float
        Target face diameter of the signet head in mm.
    ring_size : int | float | str
        Ring size in the chosen system.
    system : str
        Ring-size system: "us", "uk", "au", "eu", or "jp".
    face_height_mm : float
        Total height of the signet head above the shank, mm.
    intaglio : bool
        True = relief is recessed (intaglio seal); False = raised cameo.

    Returns
    -------
    dict with keys:
        ok : bool
        signet_spec : dict  — signet-ring node spec hint
        inner_diameter_mm : float
        relief_stats : dict — from the source mesh stats
        warnings : list[str]
    """
    if not isinstance(relief_mesh, dict) or not relief_mesh.get("ok"):
        reason = relief_mesh.get("reason", "invalid relief mesh") if isinstance(relief_mesh, dict) else "not a dict"
        return _bad(f"relief_mesh is not a valid relief result: {reason}")

    try:
        signet_face_diameter = float(signet_face_diameter)
    except (TypeError, ValueError) as exc:
        return _bad(f"signet_face_diameter must be numeric: {exc}")
    if signet_face_diameter <= 0:
        return _bad(f"signet_face_diameter must be > 0; got {signet_face_diameter}")

    try:
        face_height_mm = float(face_height_mm)
    except (TypeError, ValueError) as exc:
        return _bad(f"face_height_mm must be numeric: {exc}")
    if face_height_mm <= 0:
        return _bad(f"face_height_mm must be > 0; got {face_height_mm}")

    # Resolve ring inner diameter
    try:
        id_mm = _ring_size_to_id_mm(system, ring_size)
    except Exception as exc:
        return _bad(f"could not resolve ring size: {exc}")

    if id_mm <= 0:
        return _bad(f"ring inner_diameter_mm must be > 0; got {id_mm}")

    # The signet face must fit over the finger
    min_face_dia = id_mm + 2.0  # at least 1 mm shank wall per side
    warnings: List[str] = []
    if signet_face_diameter < min_face_dia:
        warnings.append(
            f"signet_face_diameter ({signet_face_diameter:.2f} mm) is less than "
            f"inner_diameter_mm + 2 mm ({min_face_dia:.2f} mm); "
            "the face may be too narrow to seat properly on the shank."
        )

    stats = relief_mesh.get("stats", {})
    max_depth = stats.get("max_depth_mm", 0.0)
    if max_depth >= face_height_mm:
        warnings.append(
            f"relief max_depth_mm ({max_depth:.3f}) >= face_height_mm "
            f"({face_height_mm:.3f}); reducing face_height_mm to "
            f"{max_depth + 0.5:.3f} mm."
        )
        face_height_mm = max_depth + 0.5

    mode = "recessed" if intaglio else "raised"

    signet_spec = {
        "op": "bas_relief_signet",
        "face_shape": "circular",
        "face_diameter_mm": round(signet_face_diameter, 4),
        "face_height_mm": round(face_height_mm, 4),
        "inner_diameter_mm": round(id_mm, 4),
        "intaglio_depth_mm": round(max_depth, 4),
        "mode": mode,
        "relief_stats": stats,
        "attach_points": [
            {
                "type": "signet_face",
                "role": "bas_relief",
                "position_mm": [0.0, 0.0, round(face_height_mm, 4)],
                "normal": [0.0, 0.0, 1.0],
                "diameter_mm": round(signet_face_diameter, 4),
            }
        ],
    }

    return {
        "ok": True,
        "signet_spec": signet_spec,
        "inner_diameter_mm": round(id_mm, 4),
        "relief_stats": stats,
        "warnings": warnings,
    }


def _ring_size_to_id_mm(system: str, size) -> float:
    """Minimal ring-size → inner diameter resolver (mirrors ring.py logic)."""
    sys_key = str(system).strip().lower()
    if sys_key in ("us",):
        sz = _parse_us_size(size)
        return _US_ID_INTERCEPT + _US_ID_SLOPE * sz
    elif sys_key in ("uk", "au"):
        # UK circumference table (abbreviated; full table in ring.py)
        _UK_CIRC = {
            "A": 37.8, "B": 39.1, "C": 40.4, "D": 41.7, "E": 43.0,
            "F": 44.2, "G": 45.5, "H": 46.8, "I": 48.0, "J": 49.3,
            "K": 50.6, "L": 51.9, "M": 53.1, "N": 54.4, "O": 55.7,
            "P": 57.0, "Q": 58.3, "R": 59.5, "S": 60.8, "T": 62.1,
            "U": 63.4, "V": 64.6, "W": 65.9, "X": 67.2, "Y": 68.5,
            "Z": 69.7,
        }
        key = str(size).strip().upper()
        if key not in _UK_CIRC:
            raise ValueError(f"unknown UK/AU ring size {size!r}")
        return _UK_CIRC[key] / math.pi
    elif sys_key == "eu":
        circ = float(size)
        return circ / math.pi
    elif sys_key == "jp":
        # JP: approx circumference = int(size) + 37 mm
        jp_sz = int(float(size))
        circ = jp_sz + 37.0
        return circ / math.pi
    else:
        raise ValueError(f"unknown ring-size system {system!r}")


def _parse_us_size(size) -> float:
    if isinstance(size, (int, float)):
        return float(size)
    s = str(size).strip().replace("½", ".5").replace("¼", ".25").replace("¾", ".75")
    return float(s)


# ---------------------------------------------------------------------------
# 3. relief_metal_volume_mm3
# ---------------------------------------------------------------------------

def relief_metal_volume_mm3(relief_mesh: dict) -> float:
    """Estimate displaced metal volume for casting cost estimation.

    Integrates the relief depth over the mesh surface using the mean depth
    of each triangular face times its projected XY area.

    Parameters
    ----------
    relief_mesh : dict
        Output from ``image_to_relief``.

    Returns
    -------
    float — estimated volume in mm³, or 0.0 on error.
    """
    if not isinstance(relief_mesh, dict) or not relief_mesh.get("ok"):
        return 0.0

    verts = relief_mesh.get("verts", [])
    faces = relief_mesh.get("faces", [])

    if not verts or not faces:
        return 0.0

    total_vol = 0.0
    for tri in faces:
        if len(tri) < 3:
            continue
        try:
            i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
            v0 = verts[i0]
            v1 = verts[i1]
            v2 = verts[i2]
        except (IndexError, TypeError, ValueError):
            continue

        # 2-D cross product for projected XY area
        ax = float(v1[0]) - float(v0[0])
        ay = float(v1[1]) - float(v0[1])
        bx = float(v2[0]) - float(v0[0])
        by = float(v2[1]) - float(v0[1])
        xy_area = abs(ax * by - ay * bx) * 0.5

        # Mean depth of triangle (z component)
        mean_z = (float(v0[2]) + float(v1[2]) + float(v2[2])) / 3.0
        total_vol += xy_area * mean_z

    return round(total_vol, 4)


# ---------------------------------------------------------------------------
# 4. optimize_for_casting
# ---------------------------------------------------------------------------

def optimize_for_casting(
    relief_mesh: dict,
    min_feature_mm: float = 0.4,
    smooth_passes: int = 2,
) -> dict:
    """Smooth fine-feature spikes that won't cast cleanly.

    Any vertex with Z above the local neighbourhood average by more than
    ``min_feature_mm`` is considered a casting-risk spike.  Smoothing is
    applied as a weighted average with neighbours in vertex space.

    Parameters
    ----------
    relief_mesh : dict
        Output from ``image_to_relief``.
    min_feature_mm : float
        Spike threshold in mm.  Vertices protruding more than this above
        their neighbourhood are candidates for smoothing.
    smooth_passes : int
        Number of smoothing rounds.  Default 2.

    Returns
    -------
    dict with keys:
        ok : bool
        verts : list[list[float]]  — smoothed vertex array
        faces : list[list[int]]    — unchanged face array
        delta_features : int       — number of spikes flattened
        min_feature_mm : float
        smooth_passes : int
        warnings : list[str]
    """
    if not isinstance(relief_mesh, dict) or not relief_mesh.get("ok"):
        reason = relief_mesh.get("reason", "invalid") if isinstance(relief_mesh, dict) else "not a dict"
        return _bad(f"relief_mesh is not valid: {reason}")

    try:
        min_feature_mm = float(min_feature_mm)
        smooth_passes = max(0, int(smooth_passes))
    except (TypeError, ValueError) as exc:
        return _bad(f"invalid parameters: {exc}")

    if min_feature_mm <= 0:
        return _bad(f"min_feature_mm must be > 0; got {min_feature_mm}")

    verts_in = relief_mesh.get("verts", [])
    faces = relief_mesh.get("faces", [])

    if not verts_in:
        return _bad("relief_mesh has no vertices")

    # Deep-copy verts as mutable list
    verts: List[List[float]] = [[float(v[0]), float(v[1]), float(v[2])] for v in verts_in]
    n_verts = len(verts)

    # Build adjacency map for vertex smoothing
    adj: List[List[int]] = [[] for _ in range(n_verts)]
    for tri in faces:
        if len(tri) < 3:
            continue
        try:
            i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        except (TypeError, ValueError):
            continue
        for a, b in ((i0, i1), (i1, i2), (i2, i0)):
            if 0 <= a < n_verts and 0 <= b < n_verts:
                if b not in adj[a]:
                    adj[a].append(b)
                if a not in adj[b]:
                    adj[b].append(a)

    delta_features = 0

    for _ in range(smooth_passes):
        new_verts = [list(v) for v in verts]
        for i in range(n_verts):
            nbrs = adj[i]
            if not nbrs:
                continue
            avg_z = sum(verts[j][2] for j in nbrs) / len(nbrs)
            if verts[i][2] - avg_z > min_feature_mm:
                # Blend towards neighbourhood average
                new_verts[i][2] = (verts[i][2] + avg_z) / 2.0
                delta_features += 1
        verts = new_verts

    # Round output verts
    verts_out = [[round(v[0], 6), round(v[1], 6), round(v[2], 6)] for v in verts]

    return {
        "ok": True,
        "verts": verts_out,
        "faces": faces,
        "delta_features": delta_features,
        "min_feature_mm": round(min_feature_mm, 4),
        "smooth_passes": smooth_passes,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# 5. relief_diagnostics
# ---------------------------------------------------------------------------

def relief_diagnostics(relief_mesh: dict) -> dict:
    """Return mesh quality diagnostics.

    Parameters
    ----------
    relief_mesh : dict
        Output from ``image_to_relief`` or ``optimize_for_casting``.

    Returns
    -------
    dict with keys:
        ok : bool
        vert_count : int
        face_count : int
        min_z_mm : float         — shallowest relief depth
        max_z_mm : float         — deepest relief depth
        mean_z_mm : float        — average relief depth
        min_feature_size_mm : float   — smallest edge length in mesh
        max_overhang_deg : float      — max face overhang angle from +Z normal (°)
        bbox_x_mm : float
        bbox_y_mm : float
        bbox_z_mm : float
        warnings : list[str]
    """
    if not isinstance(relief_mesh, dict) or not relief_mesh.get("ok"):
        reason = relief_mesh.get("reason", "invalid") if isinstance(relief_mesh, dict) else "not a dict"
        return _bad(f"relief_mesh is not valid: {reason}")

    verts = relief_mesh.get("verts", [])
    faces = relief_mesh.get("faces", [])

    if not verts:
        return _bad("relief_mesh has no vertices")

    warnings: List[str] = []

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]

    min_z = min(zs)
    max_z = max(zs)
    mean_z = sum(zs) / len(zs)
    bbox_x = max(xs) - min(xs)
    bbox_y = max(ys) - min(ys)
    bbox_z = max_z - min_z

    # Min feature size: smallest edge length
    min_edge = math.inf
    max_overhang = 0.0

    for tri in faces:
        if len(tri) < 3:
            continue
        try:
            i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
            v0 = verts[i0]
            v1 = verts[i1]
            v2 = verts[i2]
        except (IndexError, TypeError, ValueError):
            continue

        # Edge lengths
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            d = math.sqrt(
                (float(a[0]) - float(b[0])) ** 2 +
                (float(a[1]) - float(b[1])) ** 2 +
                (float(a[2]) - float(b[2])) ** 2
            )
            if d > 1e-9 and d < min_edge:
                min_edge = d

        # Face normal (for overhang check)
        ax = float(v1[0]) - float(v0[0])
        ay = float(v1[1]) - float(v0[1])
        az = float(v1[2]) - float(v0[2])
        bx = float(v2[0]) - float(v0[0])
        by = float(v2[1]) - float(v0[1])
        bz = float(v2[2]) - float(v0[2])
        nx = ay * bz - az * by
        ny = az * bx - ax * bz
        nz = ax * by - ay * bx
        nlen = math.sqrt(nx * nx + ny * ny + nz * nz)
        if nlen > 1e-12:
            cos_a = abs(nz / nlen)
            angle_from_z = math.degrees(math.acos(_clamp(cos_a, 0.0, 1.0)))
            if angle_from_z > max_overhang:
                max_overhang = angle_from_z

    if min_edge == math.inf:
        min_edge = 0.0

    if max_overhang > 45.0:
        warnings.append(
            f"max_overhang_deg ({max_overhang:.1f}°) exceeds 45°; "
            "some faces may require support for casting or printing."
        )
    if min_edge < 0.1:
        warnings.append(
            f"min_feature_size_mm ({min_edge:.4f}) is below 0.1 mm; "
            "features may not resolve in casting."
        )

    return {
        "ok": True,
        "vert_count": len(verts),
        "face_count": len(faces),
        "min_z_mm": round(min_z, 4),
        "max_z_mm": round(max_z, 4),
        "mean_z_mm": round(mean_z, 4),
        "min_feature_size_mm": round(min_edge, 4),
        "max_overhang_deg": round(max_overhang, 2),
        "bbox_x_mm": round(bbox_x, 4),
        "bbox_y_mm": round(bbox_y, 4),
        "bbox_z_mm": round(bbox_z, 4),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# LLM tool: jewelry_image_to_relief
# ---------------------------------------------------------------------------

_jewelry_image_to_relief_spec = ToolSpec(
    name="jewelry_image_to_relief",
    description=(
        "Convert a 2-D grayscale image (height map) to a bas-relief mesh "
        "suitable for casting a coin, medal, or signet face.\n\n"
        "Accepts a flat list-of-lists representing pixel intensities (0-1). "
        "High values produce tall relief; low values produce shallow relief.\n\n"
        "Styles: linear (proportional), gamma-curve (non-linear contrast), "
        "sigmoid (S-curve contrast), edge-enhanced (accentuates fine detail).\n\n"
        "Returns an indexed-triangle mesh (verts + faces) with casting stats."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "image_rows": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": "2-D grayscale intensity grid (rows × cols), values in [0, 1].",
            },
            "target_dia_mm": {
                "type": "number",
                "description": "Target piece diameter or width in mm.",
            },
            "max_depth_mm": {
                "type": "number",
                "description": "Maximum relief depth at full-white pixels, in mm.",
            },
            "style": {
                "type": "string",
                "enum": sorted(_VALID_STYLES),
                "description": "Depth mapping style. Default 'linear'.",
            },
            "boundary": {
                "type": "string",
                "enum": sorted(_VALID_BOUNDARY),
                "description": "'circular' disk or 'square'. Default 'circular'.",
            },
            "border_frac": {
                "type": "number",
                "description": "Border ring width as fraction of radius (0–0.5). Default 0.08.",
            },
            "gamma": {
                "type": "number",
                "description": "Gamma exponent for 'gamma-curve' style. Default 0.45.",
            },
            "edge_weight": {
                "type": "number",
                "description": "Laplacian weight for 'edge-enhanced' style. Default 0.25.",
            },
            "shrinkage_compensation": {
                "type": "boolean",
                "description": "Scale XY by 1/0.985 to compensate 1.5% casting shrinkage. Default true.",
            },
            "smooth_passes": {
                "type": "integer",
                "description": "Pre-mesh box-smoothing passes. Default 0.",
            },
        },
        "required": ["image_rows", "target_dia_mm", "max_depth_mm"],
    },
)


@register(_jewelry_image_to_relief_spec, write=False)
async def run_jewelry_image_to_relief(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    image_rows = a.get("image_rows")
    if image_rows is None:
        return err_payload("image_rows is required", "BAD_ARGS")

    try:
        target_dia_mm = float(a["target_dia_mm"])
        max_depth_mm = float(a["max_depth_mm"])
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(f"target_dia_mm and max_depth_mm required: {exc}", "BAD_ARGS")

    result = image_to_relief(
        image_rows,
        target_dia_mm,
        max_depth_mm,
        style=a.get("style", "linear"),
        boundary=a.get("boundary", "circular"),
        border_frac=float(a.get("border_frac", _DEFAULT_BORDER_FRAC)),
        gamma=float(a.get("gamma", _DEFAULT_GAMMA)),
        edge_weight=float(a.get("edge_weight", _DEFAULT_EDGE_WEIGHT)),
        shrinkage_compensation=bool(a.get("shrinkage_compensation", True)),
        smooth_passes=int(a.get("smooth_passes", 0)),
    )

    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")

    return ok_payload(result)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_relief_to_signet
# ---------------------------------------------------------------------------

_jewelry_relief_to_signet_spec = ToolSpec(
    name="jewelry_relief_to_signet",
    description=(
        "Embed a bas-relief mesh into a signet-ring head node spec.\n\n"
        "Takes the output of jewelry_image_to_relief and produces a signet "
        "ring head descriptor with correct inner diameter for the chosen ring "
        "size.  The relief is embedded as intaglio (recessed) by default, "
        "suitable for wax-seal / signet use.\n\n"
        "Required: relief_mesh (from jewelry_image_to_relief), "
        "signet_face_diameter, ring_size."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "relief_mesh": {
                "type": "object",
                "description": "Output dict from jewelry_image_to_relief.",
            },
            "signet_face_diameter": {
                "type": "number",
                "description": "Diameter of the signet face in mm.",
            },
            "ring_size": {
                "description": "Ring size in the chosen system.",
            },
            "system": {
                "type": "string",
                "enum": ["us", "uk", "au", "eu", "jp"],
                "description": "Ring-size system. Default 'us'.",
            },
            "face_height_mm": {
                "type": "number",
                "description": "Total height of the signet head above the shank, mm. Default 3.0.",
            },
            "intaglio": {
                "type": "boolean",
                "description": "True = recessed intaglio seal; False = raised cameo. Default true.",
            },
        },
        "required": ["relief_mesh", "signet_face_diameter", "ring_size"],
    },
)


@register(_jewelry_relief_to_signet_spec, write=False)
async def run_jewelry_relief_to_signet(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    relief_mesh = a.get("relief_mesh")
    if not isinstance(relief_mesh, dict):
        return err_payload("relief_mesh is required and must be a dict", "BAD_ARGS")

    try:
        signet_face_diameter = float(a["signet_face_diameter"])
        ring_size = a["ring_size"]
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(f"signet_face_diameter and ring_size required: {exc}", "BAD_ARGS")

    result = relief_to_signet(
        relief_mesh,
        signet_face_diameter,
        ring_size,
        system=a.get("system", "us"),
        face_height_mm=float(a.get("face_height_mm", 3.0)),
        intaglio=bool(a.get("intaglio", True)),
    )

    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")

    return ok_payload(result)


# ---------------------------------------------------------------------------
# LLM tool: jewelry_relief_metal_volume
# ---------------------------------------------------------------------------

_jewelry_relief_metal_volume_spec = ToolSpec(
    name="jewelry_relief_metal_volume",
    description=(
        "Estimate the displaced metal volume (mm³) of a bas-relief mesh.\n\n"
        "Useful for casting cost calculation: multiply by metal density to "
        "get added mass.  Takes the output of jewelry_image_to_relief."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "relief_mesh": {
                "type": "object",
                "description": "Output dict from jewelry_image_to_relief.",
            },
        },
        "required": ["relief_mesh"],
    },
)


@register(_jewelry_relief_metal_volume_spec, write=False)
async def run_jewelry_relief_metal_volume(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    relief_mesh = a.get("relief_mesh")
    if not isinstance(relief_mesh, dict):
        return err_payload("relief_mesh is required", "BAD_ARGS")

    vol = relief_metal_volume_mm3(relief_mesh)
    return ok_payload({"volume_mm3": vol})


# ---------------------------------------------------------------------------
# LLM tool: jewelry_optimize_relief_for_casting
# ---------------------------------------------------------------------------

_jewelry_optimize_relief_spec = ToolSpec(
    name="jewelry_optimize_relief_for_casting",
    description=(
        "Smooth fine-feature spikes in a bas-relief mesh that would not cast "
        "cleanly.\n\n"
        "Vertices protruding more than min_feature_mm above their neighbourhood "
        "are iteratively blended with their neighbours.  Returns an updated mesh "
        "with delta_features reporting how many spikes were modified."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "relief_mesh": {
                "type": "object",
                "description": "Output dict from jewelry_image_to_relief.",
            },
            "min_feature_mm": {
                "type": "number",
                "description": "Spike threshold in mm. Default 0.4.",
            },
            "smooth_passes": {
                "type": "integer",
                "description": "Number of smoothing rounds. Default 2.",
            },
        },
        "required": ["relief_mesh"],
    },
)


@register(_jewelry_optimize_relief_spec, write=False)
async def run_jewelry_optimize_relief_for_casting(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    relief_mesh = a.get("relief_mesh")
    if not isinstance(relief_mesh, dict):
        return err_payload("relief_mesh is required", "BAD_ARGS")

    result = optimize_for_casting(
        relief_mesh,
        min_feature_mm=float(a.get("min_feature_mm", 0.4)),
        smooth_passes=int(a.get("smooth_passes", 2)),
    )

    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")

    return ok_payload(result)
