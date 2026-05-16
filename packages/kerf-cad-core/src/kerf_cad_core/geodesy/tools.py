"""
kerf_cad_core.geodesy.tools — LLM tool wrappers for geodetic computation.

Registers tools with the Kerf tool registry:

  geodesy_utm_fwd            — geodetic → UTM (forward)
  geodesy_utm_inv            — UTM → geodetic (inverse)
  geodesy_vincenty_inverse   — geodesic distance & azimuths (Vincenty)
  geodesy_vincenty_direct    — destination from start + azimuth + distance
  geodesy_haversine          — great-circle distance (sphere)
  geodesy_rhumb_line         — rhumb-line distance & bearing
  geodesy_ecef_round_trip    — geodetic → ECEF → geodetic round-trip check
  geodesy_enu                — ECEF → ENU relative to reference point
  geodesy_lcc_fwd            — Lambert Conformal Conic forward
  geodesy_web_mercator_fwd   — Web Mercator (EPSG:3857) forward
  geodesy_web_mercator_inv   — Web Mercator (EPSG:3857) inverse
  geodesy_radius_curvature   — M & N radii at a latitude
  geodesy_grid_to_ground     — grid ↔ ground combined scale factor

Pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Vincenty (1975) "Direct and inverse solutions of geodesics on the ellipsoid"
Karney (2011) "Transverse Mercator with an accuracy of a few nanometres"
EPSG Guidance Note 7-2 (2023) — Map projections

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.geodesy.geo import (
    utm_fwd,
    utm_inv,
    vincenty_inverse,
    vincenty_direct,
    haversine,
    rhumb_line,
    geodetic_to_ecef,
    ecef_to_geodetic,
    ecef_to_enu,
    lcc_fwd,
    web_mercator_fwd,
    web_mercator_inv,
    radius_curvature,
    grid_to_ground,
)


# ---------------------------------------------------------------------------
# Tool: geodesy_utm_fwd
# ---------------------------------------------------------------------------

_utm_fwd_spec = ToolSpec(
    name="geodesy_utm_fwd",
    description=(
        "Forward UTM projection: convert geodetic (lat, lon) to UTM easting/northing.\n"
        "\n"
        "Ellipsoid: WGS84 (default), GRS80, or Clarke1866.\n"
        "Zone is derived from longitude if not supplied.\n"
        "\n"
        "Returns easting_m, northing_m, zone, hemisphere (N/S), "
        "point scale factor k, and meridian convergence gamma_deg.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat_deg": {
                "type": "number",
                "description": "Geodetic latitude (degrees, –90..90).",
            },
            "lon_deg": {
                "type": "number",
                "description": "Geodetic longitude (degrees, –180..180).",
            },
            "zone": {
                "type": "integer",
                "description": "UTM zone (1–60). Derived from lon_deg if omitted.",
            },
            "ellipsoid": {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["lat_deg", "lon_deg"],
    },
)


@register(_utm_fwd_spec, write=False)
async def run_utm_fwd(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    if a.get("lat_deg") is None:
        return json.dumps({"ok": False, "reason": "lat_deg is required"})
    if a.get("lon_deg") is None:
        return json.dumps({"ok": False, "reason": "lon_deg is required"})

    kwargs: dict = {}
    if "zone" in a:
        kwargs["zone"] = a["zone"]
    if "ellipsoid" in a:
        kwargs["ellipsoid"] = a["ellipsoid"]

    try:
        result = utm_fwd(a["lat_deg"], a["lon_deg"], **kwargs)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_utm_inv
# ---------------------------------------------------------------------------

_utm_inv_spec = ToolSpec(
    name="geodesy_utm_inv",
    description=(
        "Inverse UTM projection: convert UTM easting/northing to geodetic (lat, lon).\n"
        "\n"
        "Returns lat_deg, lon_deg, point scale factor k, meridian convergence gamma_deg.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "easting_m": {
                "type": "number",
                "description": "UTM easting (metres).",
            },
            "northing_m": {
                "type": "number",
                "description": "UTM northing (metres).",
            },
            "zone": {
                "type": "integer",
                "description": "UTM zone (1–60).",
            },
            "hemisphere": {
                "type": "string",
                "enum": ["N", "S"],
                "description": "Hemisphere 'N' (default) or 'S'.",
            },
            "ellipsoid": {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["easting_m", "northing_m", "zone"],
    },
)


@register(_utm_inv_spec, write=False)
async def run_utm_inv(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    for f in ("easting_m", "northing_m", "zone"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "hemisphere" in a:
        kwargs["hemisphere"] = a["hemisphere"]
    if "ellipsoid" in a:
        kwargs["ellipsoid"] = a["ellipsoid"]

    try:
        result = utm_inv(a["easting_m"], a["northing_m"], a["zone"], **kwargs)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_vincenty_inverse
# ---------------------------------------------------------------------------

_vincenty_inv_spec = ToolSpec(
    name="geodesy_vincenty_inverse",
    description=(
        "Vincenty (1975) inverse solution: geodesic distance and azimuths "
        "between two geodetic points on the ellipsoid.\n"
        "\n"
        "More accurate than Haversine for geodetic use (sub-millimetre).\n"
        "For nearly antipodal points Vincenty may not converge; in that case "
        "a Haversine fallback is used and convergence_warning is set to true.\n"
        "\n"
        "Returns distance_m, forward azimuth az12_deg, back azimuth az21_deg, "
        "and convergence_warning.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat1_deg": {"type": "number", "description": "Start latitude (degrees)."},
            "lon1_deg": {"type": "number", "description": "Start longitude (degrees)."},
            "lat2_deg": {"type": "number", "description": "End latitude (degrees)."},
            "lon2_deg": {"type": "number", "description": "End longitude (degrees)."},
            "ellipsoid": {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["lat1_deg", "lon1_deg", "lat2_deg", "lon2_deg"],
    },
)


@register(_vincenty_inv_spec, write=False)
async def run_vincenty_inverse(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    for f in ("lat1_deg", "lon1_deg", "lat2_deg", "lon2_deg"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "ellipsoid" in a:
        kwargs["ellipsoid"] = a["ellipsoid"]

    try:
        result = vincenty_inverse(
            a["lat1_deg"], a["lon1_deg"], a["lat2_deg"], a["lon2_deg"], **kwargs
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_vincenty_direct
# ---------------------------------------------------------------------------

_vincenty_dir_spec = ToolSpec(
    name="geodesy_vincenty_direct",
    description=(
        "Vincenty (1975) direct solution: compute destination geodetic point "
        "given start point, forward azimuth, and geodesic distance.\n"
        "\n"
        "Returns lat2_deg, lon2_deg, back azimuth az21_deg, and convergence_warning.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat1_deg":  {"type": "number", "description": "Start latitude (degrees)."},
            "lon1_deg":  {"type": "number", "description": "Start longitude (degrees)."},
            "az12_deg":  {"type": "number", "description": "Forward azimuth from start (degrees, 0=N clockwise)."},
            "dist_m":    {"type": "number", "description": "Geodesic distance (metres). Must be >= 0."},
            "ellipsoid": {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["lat1_deg", "lon1_deg", "az12_deg", "dist_m"],
    },
)


@register(_vincenty_dir_spec, write=False)
async def run_vincenty_direct(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    for f in ("lat1_deg", "lon1_deg", "az12_deg", "dist_m"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "ellipsoid" in a:
        kwargs["ellipsoid"] = a["ellipsoid"]

    try:
        result = vincenty_direct(
            a["lat1_deg"], a["lon1_deg"], a["az12_deg"], a["dist_m"], **kwargs
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_haversine
# ---------------------------------------------------------------------------

_haversine_spec = ToolSpec(
    name="geodesy_haversine",
    description=(
        "Haversine great-circle distance between two points on a sphere.\n"
        "\n"
        "Suitable for quick distance estimates. For geodetic accuracy use "
        "geodesy_vincenty_inverse instead.\n"
        "\n"
        "Default sphere radius is IUGG mean Earth radius (6 371 008.8 m).\n"
        "\n"
        "Returns distance_m, forward azimuth az12_deg, back azimuth az21_deg.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat1_deg":   {"type": "number", "description": "Start latitude (degrees)."},
            "lon1_deg":   {"type": "number", "description": "Start longitude (degrees)."},
            "lat2_deg":   {"type": "number", "description": "End latitude (degrees)."},
            "lon2_deg":   {"type": "number", "description": "End longitude (degrees)."},
            "radius_m":   {
                "type": "number",
                "description": "Sphere radius (metres). Default 6 371 008.8 m (IUGG mean).",
            },
        },
        "required": ["lat1_deg", "lon1_deg", "lat2_deg", "lon2_deg"],
    },
)


@register(_haversine_spec, write=False)
async def run_haversine(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    for f in ("lat1_deg", "lon1_deg", "lat2_deg", "lon2_deg"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "radius_m" in a:
        kwargs["radius_m"] = a["radius_m"]

    try:
        result = haversine(
            a["lat1_deg"], a["lon1_deg"], a["lat2_deg"], a["lon2_deg"], **kwargs
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_rhumb_line
# ---------------------------------------------------------------------------

_rhumb_spec = ToolSpec(
    name="geodesy_rhumb_line",
    description=(
        "Rhumb-line (loxodrome) distance and constant bearing between two geodetic points.\n"
        "\n"
        "A rhumb line crosses all meridians at the same angle. Unlike a great circle, "
        "it gives a constant compass bearing throughout the journey.\n"
        "\n"
        "Returns distance_m and bearing_deg (0=N, 90=E, clockwise).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat1_deg":  {"type": "number", "description": "Start latitude (degrees)."},
            "lon1_deg":  {"type": "number", "description": "Start longitude (degrees)."},
            "lat2_deg":  {"type": "number", "description": "End latitude (degrees)."},
            "lon2_deg":  {"type": "number", "description": "End longitude (degrees)."},
            "ellipsoid": {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["lat1_deg", "lon1_deg", "lat2_deg", "lon2_deg"],
    },
)


@register(_rhumb_spec, write=False)
async def run_rhumb_line(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    for f in ("lat1_deg", "lon1_deg", "lat2_deg", "lon2_deg"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "ellipsoid" in a:
        kwargs["ellipsoid"] = a["ellipsoid"]

    try:
        result = rhumb_line(
            a["lat1_deg"], a["lon1_deg"], a["lat2_deg"], a["lon2_deg"], **kwargs
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_ecef_round_trip
# ---------------------------------------------------------------------------

_ecef_spec = ToolSpec(
    name="geodesy_ecef_round_trip",
    description=(
        "Convert geodetic (lat, lon, h) → ECEF (X, Y, Z) and back, "
        "returning both ECEF coordinates and the recovered geodetic coordinates.\n"
        "\n"
        "Useful for validating coordinate transform pipelines.\n"
        "Round-trip error is typically < 10 nm on WGS84.\n"
        "\n"
        "Returns X_m, Y_m, Z_m and recovered lat_deg, lon_deg, h_m.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat_deg":   {"type": "number", "description": "Geodetic latitude (degrees, –90..90)."},
            "lon_deg":   {"type": "number", "description": "Geodetic longitude (degrees, –180..180)."},
            "h_m":       {"type": "number", "description": "Ellipsoidal height (metres, default 0)."},
            "ellipsoid": {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["lat_deg", "lon_deg"],
    },
)


@register(_ecef_spec, write=False)
async def run_ecef_round_trip(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    if a.get("lat_deg") is None:
        return json.dumps({"ok": False, "reason": "lat_deg is required"})
    if a.get("lon_deg") is None:
        return json.dumps({"ok": False, "reason": "lon_deg is required"})

    h_m = a.get("h_m", 0.0)
    ell = a.get("ellipsoid", None)

    try:
        ecef = geodetic_to_ecef(a["lat_deg"], a["lon_deg"], h_m, ell)
        geo  = ecef_to_geodetic(ecef["X_m"], ecef["Y_m"], ecef["Z_m"], ell)
        result = {
            "X_m": ecef["X_m"],
            "Y_m": ecef["Y_m"],
            "Z_m": ecef["Z_m"],
            "recovered_lat_deg": geo["lat_deg"],
            "recovered_lon_deg": geo["lon_deg"],
            "recovered_h_m":     geo["h_m"],
        }
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_enu
# ---------------------------------------------------------------------------

_enu_spec = ToolSpec(
    name="geodesy_enu",
    description=(
        "Convert a geodetic point to ENU (East-North-Up) local tangent plane "
        "coordinates relative to a reference origin.\n"
        "\n"
        "Returns e_m (east), n_m (north), u_m (up) in metres.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat_deg":     {"type": "number", "description": "Point latitude (degrees)."},
            "lon_deg":     {"type": "number", "description": "Point longitude (degrees)."},
            "h_m":         {"type": "number", "description": "Point ellipsoidal height (metres, default 0)."},
            "ref_lat_deg": {"type": "number", "description": "Reference origin latitude (degrees)."},
            "ref_lon_deg": {"type": "number", "description": "Reference origin longitude (degrees)."},
            "ref_h_m":     {"type": "number", "description": "Reference origin height (metres, default 0)."},
            "ellipsoid":   {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["lat_deg", "lon_deg", "ref_lat_deg", "ref_lon_deg"],
    },
)


@register(_enu_spec, write=False)
async def run_enu(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    for f in ("lat_deg", "lon_deg", "ref_lat_deg", "ref_lon_deg"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    h_m     = a.get("h_m", 0.0)
    ref_h_m = a.get("ref_h_m", 0.0)
    ell     = a.get("ellipsoid", None)

    try:
        ecef = geodetic_to_ecef(a["lat_deg"], a["lon_deg"], h_m, ell)
        result = ecef_to_enu(
            ecef["X_m"], ecef["Y_m"], ecef["Z_m"],
            a["ref_lat_deg"], a["ref_lon_deg"], ref_h_m,
            ell,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_lcc_fwd
# ---------------------------------------------------------------------------

_lcc_fwd_spec = ToolSpec(
    name="geodesy_lcc_fwd",
    description=(
        "Lambert Conformal Conic (LCC) forward projection.\n"
        "\n"
        "Supports 1-parallel (lat2_deg omitted or equal to lat1_deg) "
        "and 2-parallel configurations.\n"
        "\n"
        "Returns easting_m, northing_m, point scale factor k.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat_deg":   {"type": "number", "description": "Point latitude (degrees)."},
            "lon_deg":   {"type": "number", "description": "Point longitude (degrees)."},
            "lat0_deg":  {"type": "number", "description": "Latitude of false origin (degrees)."},
            "lon0_deg":  {"type": "number", "description": "Central meridian (degrees)."},
            "lat1_deg":  {"type": "number", "description": "First standard parallel (degrees)."},
            "lat2_deg":  {"type": "number", "description": "Second standard parallel (degrees). Omit for 1-parallel."},
            "FE":        {"type": "number", "description": "False easting (metres, default 0)."},
            "FN":        {"type": "number", "description": "False northing (metres, default 0)."},
            "ellipsoid": {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["lat_deg", "lon_deg", "lat0_deg", "lon0_deg", "lat1_deg"],
    },
)


@register(_lcc_fwd_spec, write=False)
async def run_lcc_fwd(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    for f in ("lat_deg", "lon_deg", "lat0_deg", "lon0_deg", "lat1_deg"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "lat2_deg" in a:
        kwargs["lat2_deg"] = a["lat2_deg"]
    if "FE" in a:
        kwargs["FE"] = a["FE"]
    if "FN" in a:
        kwargs["FN"] = a["FN"]
    if "ellipsoid" in a:
        kwargs["ellipsoid"] = a["ellipsoid"]

    try:
        result = lcc_fwd(
            a["lat_deg"], a["lon_deg"],
            a["lat0_deg"], a["lon0_deg"], a["lat1_deg"],
            **kwargs
        )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_web_mercator_fwd
# ---------------------------------------------------------------------------

_wm_fwd_spec = ToolSpec(
    name="geodesy_web_mercator_fwd",
    description=(
        "Web Mercator (EPSG:3857 / Pseudo Mercator) forward projection.\n"
        "\n"
        "Spherical projection using WGS84 semi-major axis as sphere radius. "
        "Valid latitude range ±85.05°.\n"
        "\n"
        "Returns x_m, y_m in metres.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat_deg": {"type": "number", "description": "Latitude (degrees, –85.05..85.05)."},
            "lon_deg": {"type": "number", "description": "Longitude (degrees, –180..180)."},
        },
        "required": ["lat_deg", "lon_deg"],
    },
)


@register(_wm_fwd_spec, write=False)
async def run_web_mercator_fwd(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    if a.get("lat_deg") is None:
        return json.dumps({"ok": False, "reason": "lat_deg is required"})
    if a.get("lon_deg") is None:
        return json.dumps({"ok": False, "reason": "lon_deg is required"})

    try:
        result = web_mercator_fwd(a["lat_deg"], a["lon_deg"])
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_web_mercator_inv
# ---------------------------------------------------------------------------

_wm_inv_spec = ToolSpec(
    name="geodesy_web_mercator_inv",
    description=(
        "Web Mercator (EPSG:3857) inverse projection.\n"
        "\n"
        "Returns lat_deg, lon_deg.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "x_m": {"type": "number", "description": "Web Mercator x coordinate (metres)."},
            "y_m": {"type": "number", "description": "Web Mercator y coordinate (metres)."},
        },
        "required": ["x_m", "y_m"],
    },
)


@register(_wm_inv_spec, write=False)
async def run_web_mercator_inv(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    if a.get("x_m") is None:
        return json.dumps({"ok": False, "reason": "x_m is required"})
    if a.get("y_m") is None:
        return json.dumps({"ok": False, "reason": "y_m is required"})

    try:
        result = web_mercator_inv(a["x_m"], a["y_m"])
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_radius_curvature
# ---------------------------------------------------------------------------

_rc_spec = ToolSpec(
    name="geodesy_radius_curvature",
    description=(
        "Compute radii of curvature M (meridian) and N (prime vertical) "
        "at a geodetic latitude.\n"
        "\n"
        "M = radius of curvature in the meridian plane.\n"
        "N = radius of curvature in the prime vertical plane (transverse).\n"
        "\n"
        "Returns M_m and N_m in metres.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lat_deg":   {"type": "number", "description": "Geodetic latitude (degrees, –90..90)."},
            "ellipsoid": {
                "type": "string",
                "enum": ["WGS84", "GRS80", "Clarke1866"],
                "description": "Reference ellipsoid (default WGS84).",
            },
        },
        "required": ["lat_deg"],
    },
)


@register(_rc_spec, write=False)
async def run_radius_curvature(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    if a.get("lat_deg") is None:
        return json.dumps({"ok": False, "reason": "lat_deg is required"})

    kwargs: dict = {}
    if "ellipsoid" in a:
        kwargs["ellipsoid"] = a["ellipsoid"]

    try:
        result = radius_curvature(a["lat_deg"], **kwargs)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tool: geodesy_grid_to_ground
# ---------------------------------------------------------------------------

_g2g_spec = ToolSpec(
    name="geodesy_grid_to_ground",
    description=(
        "Convert a grid distance to ground distance using the combined scale factor (CSF).\n"
        "\n"
        "CSF = k_projection × k_elevation\n"
        "k_elevation = R / (R + h)\n"
        "ground_distance = grid_distance / CSF\n"
        "\n"
        "Used in surveying to account for both the projection distortion and "
        "the elevation above the ellipsoid.\n"
        "\n"
        "Returns ground_distance_m, csf, and k_elevation.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "grid_distance_m": {
                "type": "number",
                "description": "Horizontal grid distance (metres).",
            },
            "elevation_m": {
                "type": "number",
                "description": "Mean elevation above ellipsoid at the line midpoint (metres).",
            },
            "k_projection": {
                "type": "number",
                "description": "Projection scale factor at the line midpoint (from UTM or other projection).",
            },
            "earth_radius_m": {
                "type": "number",
                "description": "Mean Earth radius (metres, default 6 371 000).",
            },
        },
        "required": ["grid_distance_m", "elevation_m", "k_projection"],
    },
)


@register(_g2g_spec, write=False)
async def run_grid_to_ground(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})

    for f in ("grid_distance_m", "elevation_m", "k_projection"):
        if a.get(f) is None:
            return json.dumps({"ok": False, "reason": f"{f} is required"})

    kwargs: dict = {}
    if "earth_radius_m" in a:
        kwargs["earth_radius_m"] = a["earth_radius_m"]

    try:
        result = grid_to_ground(a["grid_distance_m"], a["elevation_m"], a["k_projection"], **kwargs)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    return json.dumps({"ok": True, **result})
