"""routes_composites_mfg.py — manufacturing-UI endpoints for Wave 4D panels.

Closes the caveat opened by commit 9a222c43.  Three frontend panels dispatch to:

  POST /api/composites/clt       — LaminateStackup  (layup_analysis tool)
  POST /api/composites/afp       — AFPToolpathView   (composites_afp_pathplan tool)
  POST /api/composites/fiber_map — FiberOrientationContour (composites_drape tool)

All three accept the { tool, args } envelope emitted by the frontend panels.
Auth via require_auth (Depends).  Graceful 503 on missing optional deps.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kerf_core.dependencies import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitise_json(obj: Any) -> Any:
    """Replace non-finite floats with None for JSON safety."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitise_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitise_json(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# POST /api/composites/clt
#
# Frontend sends:
#   { tool: "layup_analysis",
#     args: { plies: [{angle, E1, E2, G12, nu12, thickness}], name?: str } }
#
# Returns:  A/B/D matrices + stiffness summary + weight
# ---------------------------------------------------------------------------

class _CLTMfgRequest(BaseModel):
    tool: str = Field(default="layup_analysis")
    args: Dict[str, Any] = Field(...)


@router.post("/composites/clt", tags=["composites"])
def composites_clt_mfg(req: _CLTMfgRequest, _auth: dict = Depends(require_auth)):
    """CLT ABD analysis — Wave 4D LaminateStackup panel.

    Accepts the { tool, args } envelope from the frontend.
    args.plies items use `angle` (not `angle_deg`) and SI-prefixed moduli
    in GPa (consistent with the kerf_composites.layup schema).

    Returns:
      ok              — True on success
      name            — laminate label
      num_plies       — number of plies
      total_thickness_mm
      is_symmetric
      A_matrix_N_per_mm — 3×3 list-of-lists
      B_matrix_N        — 3×3
      D_matrix_N_mm     — 3×3
      effective_moduli  — {Ex_GPa, Ey_GPa, Gxy_GPa, ...}
      weight_g_per_m2
    """
    try:
        from kerf_composites.layup import Ply, PlyMaterial, LaminateLayup
        from kerf_composites.clt import abd_matrices, effective_moduli
    except ImportError as exc:
        logger.warning("kerf_composites not available: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "pending",
                     "reason": "kerf-composites package not installed."},
        )

    args = req.args
    raw_plies: List[dict] = args.get("plies", [])
    if not raw_plies:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": "args.plies must be a non-empty list."},
        )

    plies: List[Ply] = []
    try:
        for i, rp in enumerate(raw_plies):
            mat = PlyMaterial(
                name=rp.get("material", f"ply_{i}"),
                E1=float(rp["E1"]),
                E2=float(rp["E2"]),
                G12=float(rp["G12"]),
                nu12=float(rp["nu12"]),
                Xt=float(rp.get("Xt", 1500.0)),
                Xc=float(rp.get("Xc", 1500.0)),
                Yt=float(rp.get("Yt", 40.0)),
                Yc=float(rp.get("Yc", 246.0)),
                S12=float(rp.get("S12", 68.0)),
            )
            plies.append(Ply(
                angle=float(rp.get("angle", rp.get("angle_deg", 0.0))),
                material=mat,
                thickness=float(rp["thickness"]),
            ))
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": f"Invalid ply definition: {exc}"},
        )

    name = args.get("name", "laminate")
    layup = LaminateLayup(plies=plies, name=name)
    A, B, D = abd_matrices(layup)
    moduli = effective_moduli(layup)

    def _m(mat):
        return [[round(v, 4) for v in row] for row in mat.tolist()]

    # Areal weight in g/m² — rho stored as kg/m³ on ply if present, else typical CFRP ~1600
    RHO_DEFAULT = 1600.0  # kg/m³
    weight = sum(
        (getattr(getattr(p, "material", None), "rho", None) or RHO_DEFAULT)
        * (p.thickness / 1000.0)  # mm → m
        * 1e6                       # g/m²
        for p in plies
    ) if plies else 0.0

    payload = {
        "ok": True,
        "name": layup.name,
        "num_plies": layup.num_plies,
        "total_thickness_mm": round(layup.total_thickness, 4),
        "is_symmetric": layup.is_symmetric,
        "A_matrix_N_per_mm": _m(A),
        "B_matrix_N": _m(B),
        "D_matrix_N_mm": _m(D),
        "effective_moduli": {k: round(v, 6) for k, v in moduli.items()},
        "weight_g_per_m2": round(weight, 2),
    }
    return _sanitise_json(payload)


# ---------------------------------------------------------------------------
# POST /api/composites/afp
#
# Frontend sends:
#   { tool: "composites_afp_pathplan",
#     args: { courseWidth, minRadius, towCount, angle,
#             rampRate, dwellTemp, dwellTime, coolRate } }
#
# Returns: tape path courses + cure cycle summary
# ---------------------------------------------------------------------------

class _AFPMfgRequest(BaseModel):
    tool: str = Field(default="composites_afp_pathplan")
    args: Dict[str, Any] = Field(...)


@router.post("/composites/afp", tags=["composites"])
def composites_afp(req: _AFPMfgRequest, _auth: dict = Depends(require_auth)):
    """AFP tape-path generation — Wave 4D AFPToolpathView panel.

    Generates tow courses for an Automated Fibre Placement layup and returns
    a cure-cycle summary.  No external package required; the pathplan is an
    analytical calculation.

    Returns:
      ok            — True
      tool          — echoed tool name
      courses       — list of {course_id, angle_deg, start_x, start_y,
                               end_x, end_y, tow_width_mm, length_mm}
      cure_cycle    — {ramp_rate_C_per_min, dwell_temp_C, dwell_time_min,
                       cool_rate_C_per_min, total_time_min}
      part_width_mm — default 400
      part_height_mm — default 260
      num_courses   — count
    """
    args = req.args
    try:
        course_width = float(args.get("courseWidth", 6.35))   # mm tow width
        min_radius   = float(args.get("minRadius", 600.0))    # mm steering radius
        tow_count    = int(args.get("towCount", 8))
        angle_deg    = float(args.get("angle", 0.0))
        ramp_rate    = float(args.get("rampRate", 2.0))       # °C/min
        dwell_temp   = float(args.get("dwellTemp", 180.0))    # °C
        dwell_time   = float(args.get("dwellTime", 60.0))     # min
        cool_rate    = float(args.get("coolRate", 3.0))       # °C/min
    except (TypeError, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": f"Invalid AFP parameter: {exc}"},
        )

    part_w, part_h = 400.0, 260.0  # mm — default part dimensions
    angle_rad = math.radians(angle_deg)
    c, s = math.cos(angle_rad), math.sin(angle_rad)

    # Build tow courses across the part width (simplified rectilinear AFP paths)
    # Course start/end are intersected with the part bounding box
    band_width = course_width * tow_count  # full band across all tows

    # Step between bands perpendicular to angle direction
    perp_x = -s
    perp_y = c
    # Cover the diagonal extent
    diag = math.hypot(part_w, part_h)
    n_courses = max(1, int(math.ceil(diag / band_width)))

    courses = []
    offset_start = -diag / 2.0
    for i in range(n_courses):
        offset = offset_start + i * band_width + band_width / 2.0
        # Line through part centre at given angle, offset in perp direction
        cx = part_w / 2.0 + perp_x * offset
        cy = part_h / 2.0 + perp_y * offset

        # Walk along course direction to find entry/exit on bbox
        # Parametric: (cx + c*t, cy + s*t) clipped to [0,part_w]×[0,part_h]
        t_vals = []
        if abs(c) > 1e-9:
            t_vals.extend([-cx / c, (part_w - cx) / c])
        if abs(s) > 1e-9:
            t_vals.extend([-cy / s, (part_h - cy) / s])
        t_vals = sorted(t_vals)

        def _in_box(t):
            px = cx + c * t
            py = cy + s * t
            return (-1e-6 <= px <= part_w + 1e-6) and (-1e-6 <= py <= part_h + 1e-6)

        valid = [t for t in t_vals if _in_box(t)]
        if len(valid) < 2:
            continue

        t0, t1 = valid[0], valid[-1]
        sx, sy = cx + c * t0, cy + s * t0
        ex, ey = cx + c * t1, cy + s * t1
        length = math.hypot(ex - sx, ey - sy)

        courses.append({
            "course_id": i,
            "angle_deg": round(angle_deg, 2),
            "start_x": round(sx, 2),
            "start_y": round(sy, 2),
            "end_x": round(ex, 2),
            "end_y": round(ey, 2),
            "tow_width_mm": round(course_width, 3),
            "length_mm": round(length, 2),
        })

    # Cure cycle summary
    t_ramp = (dwell_temp - 25.0) / ramp_rate
    t_cool = (dwell_temp - 25.0) / cool_rate
    total_time = t_ramp + dwell_time + t_cool

    cure_cycle = {
        "ramp_rate_C_per_min": ramp_rate,
        "dwell_temp_C": dwell_temp,
        "dwell_time_min": dwell_time,
        "cool_rate_C_per_min": cool_rate,
        "total_time_min": round(total_time, 1),
    }

    payload = {
        "ok": True,
        "tool": req.tool,
        "part_width_mm": part_w,
        "part_height_mm": part_h,
        "num_courses": len(courses),
        "courses": courses,
        "cure_cycle": cure_cycle,
    }
    return payload


# ---------------------------------------------------------------------------
# POST /api/composites/fiber_map
#
# Frontend sends:
#   { tool: "composites_drape",
#     args: { surface, u_range, v_range, nu, nv, radius } }
#
# Returns: per-element fiber angle map (shear angles + drape stats)
# ---------------------------------------------------------------------------

class _FiberMapRequest(BaseModel):
    tool: str = Field(default="composites_drape")
    args: Dict[str, Any] = Field(...)


@router.post("/composites/fiber_map", tags=["composites"])
def composites_fiber_map(req: _FiberMapRequest, _auth: dict = Depends(require_auth)):
    """Fiber-orientation drape simulation — Wave 4D FiberOrientationContour panel.

    Delegates to kerf_composites.drape (flat_surface / cylindrical_surface).

    Returns:
      ok              — True on success
      tool            — echoed tool name
      surface         — surface type
      nu, nv          — grid dimensions
      u_range, v_range
      shear_angle_deg — {mean, max, min}
      surf_coords_shape
      corner_coords_mm — 3 corner points
      fiber_angles    — flattened nu×nv array of per-node angle estimates [deg]
                        (nominal ply angle 0° + local shear deviation)
    """
    try:
        from kerf_composites.drape import (
            drape_flat_to_surface, flat_surface, cylindrical_surface,
        )
        import numpy as np
    except ImportError as exc:
        logger.warning("kerf_composites not available: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "pending",
                     "reason": "kerf-composites package not installed."},
        )

    args = req.args
    surface_type = str(args.get("surface", "flat"))
    try:
        u_range = tuple(float(x) for x in args.get("u_range", [0.0, 100.0]))
        v_range = tuple(float(x) for x in args.get("v_range", [0.0, 100.0]))
        nu      = int(args.get("nu", 10))
        nv      = int(args.get("nv", 10))
        radius  = float(args.get("radius", 100.0))
        flat_z  = float(args.get("flat_z", 0.0))
    except (TypeError, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": f"Invalid drape parameter: {exc}"},
        )

    if surface_type == "flat":
        sfn = flat_surface(z=flat_z)
    elif surface_type == "cylinder_x":
        sfn = cylindrical_surface(radius=radius, axis="x")
    elif surface_type == "cylinder_y":
        sfn = cylindrical_surface(radius=radius, axis="y")
    else:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": f"Unknown surface type: {surface_type!r}. "
                     "Use 'flat', 'cylinder_x', or 'cylinder_y'."},
        )

    try:
        result = drape_flat_to_surface(sfn, u_range, v_range, nu=nu, nv=nv)
    except Exception as exc:
        logger.exception("drape_flat_to_surface failed")
        return JSONResponse(
            status_code=422,
            content={"ok": False, "reason": str(exc)},
        )

    shear = result.shear_angles
    # Fiber angles = nominal 0° + local shear deviation (sign-preserving)
    fiber_angles = shear.flatten().tolist()

    payload = {
        "ok": True,
        "tool": req.tool,
        "surface": surface_type,
        "nu": result.nu,
        "nv": result.nv,
        "u_range": list(u_range),
        "v_range": list(v_range),
        "shear_angle_deg": {
            "mean": round(float(np.mean(shear)), 4),
            "max":  round(float(np.max(shear)), 4),
            "min":  round(float(np.min(shear)), 4),
        },
        "surf_coords_shape": list(result.surf_coords.shape),
        "corner_coords_mm": [
            [round(v, 3) for v in result.surf_coords[0, 0].tolist()],
            [round(v, 3) for v in result.surf_coords[-1, 0].tolist()],
            [round(v, 3) for v in result.surf_coords[-1, -1].tolist()],
        ],
        "fiber_angles": [round(a, 4) for a in fiber_angles],
    }
    return _sanitise_json(payload)
