"""
kerf_cad_core.cmm.tools — LLM tool wrappers for CMM inspection planning.

Registers tools with the Kerf tool registry:

  cmm_fit_geometry         — least-squares fit (line/plane/circle/sphere/cylinder)
  cmm_align_datum          — datum-reference-frame alignment (3-2-1 or best-fit)
  cmm_eval_gdt             — GD&T evaluation from measured points
  cmm_eval_position        — true-position + MMC bonus tolerance
  cmm_eval_profile         — surface profile evaluation
  cmm_gum_uncertainty      — GUM combined measurement uncertainty
  cmm_probe_compensate     — stylus-radius compensation
  cmm_recommend_samples    — Nyquist-based sampling recommendation
  cmm_gauge_rr             — Gauge R&R (ANOVA or average-range method)
  cmm_process_capability   — Cpk / Ppk process capability

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ISO 1101:2017 — Geometrical product specifications (GPS)
ASME Y14.5-2018 — Dimensioning and Tolerancing
JCGM 100:2008 — GUM: Evaluation of measurement data
AIAG MSA 4th ed. — Measurement System Analysis

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.cmm.inspect import (
    fit_line,
    fit_plane,
    fit_circle,
    fit_sphere,
    fit_cylinder,
    align_321,
    align_bestfit,
    eval_flatness,
    eval_circularity,
    eval_cylindricity,
    eval_perpendicularity,
    eval_parallelism,
    eval_angularity,
    eval_position,
    eval_profile,
    gum_uncertainty,
    probe_compensate,
    recommend_samples,
    gauge_rr_anova,
    gauge_rr_avgrange,
    process_capability,
)


# ---------------------------------------------------------------------------
# Tool: cmm_fit_geometry
# ---------------------------------------------------------------------------

_fit_geometry_spec = ToolSpec(
    name="cmm_fit_geometry",
    description=(
        "Fit a geometric primitive to a set of 3D measured points using "
        "least-squares.\n"
        "\n"
        "Supported shapes:\n"
        "  'line'     — best-fit line; returns centroid, direction, residuals.\n"
        "  'plane'    — best-fit plane; returns normal, d, form error (flatness).\n"
        "  'circle'   — best-fit circle in a plane; returns centre, radius, "
        "roundness.\n"
        "  'sphere'   — best-fit sphere; returns centre, radius, sphericity.\n"
        "  'cylinder' — best-fit cylinder; returns axis, radius, cylindricity.\n"
        "\n"
        "form_error in the response equals the applicable form tolerance zone "
        "width (peak-to-valley of radial/normal deviations).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {
                "type": "string",
                "enum": ["line", "plane", "circle", "sphere", "cylinder"],
                "description": "Geometric primitive to fit.",
            },
            "points": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "List of [x, y, z] measured points.",
                "minItems": 2,
            },
            "plane_normal": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "For 'circle' only: [nx, ny, nz] normal of the measurement "
                    "plane.  Defaults to [0, 0, 1] (XY plane) if omitted."
                ),
            },
            "axis_guess": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "For 'cylinder' only: initial axis direction [dx, dy, dz]. "
                    "If omitted, estimated from PCA."
                ),
            },
        },
        "required": ["shape", "points"],
    },
)


@register(_fit_geometry_spec, write=False)
async def run_cmm_fit_geometry(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    shape = a.get("shape")
    points = a.get("points")
    if not shape:
        return json.dumps({"ok": False, "reason": "shape is required"})
    if not points:
        return json.dumps({"ok": False, "reason": "points is required"})

    if shape == "line":
        result = fit_line(points)
    elif shape == "plane":
        result = fit_plane(points)
    elif shape == "circle":
        pn = a.get("plane_normal")
        result = fit_circle(points, pn)
    elif shape == "sphere":
        result = fit_sphere(points)
    elif shape == "cylinder":
        ag = a.get("axis_guess")
        result = fit_cylinder(points, ag)
    else:
        return json.dumps({"ok": False, "reason": f"unknown shape: {shape}"})

    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_align_datum
# ---------------------------------------------------------------------------

_align_datum_spec = ToolSpec(
    name="cmm_align_datum",
    description=(
        "Compute a datum-reference-frame (DRF) alignment transform.\n"
        "\n"
        "Two methods:\n"
        "  '3-2-1'    — Classical 3-2-1 datum alignment.  Provide "
        "primary_pts (≥3), secondary_pts (≥2), tertiary_pts (≥1).\n"
        "  'best-fit' — Minimise RMS deviation of measured to nominal "
        "corresponding points.  Provide nominal_pts and measured_pts "
        "(equal length ≥3).\n"
        "\n"
        "Returns the 4×4 homogeneous rigid transform (row-major) plus "
        "the DRF axes and translation.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["3-2-1", "best-fit"],
                "description": "Alignment method.",
            },
            "primary_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Primary datum points (≥3) for 3-2-1.",
            },
            "secondary_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Secondary datum points (≥2) for 3-2-1.",
            },
            "tertiary_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Tertiary datum points (≥1) for 3-2-1.",
            },
            "nominal_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Nominal point coordinates for best-fit.",
            },
            "measured_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Measured point coordinates for best-fit.",
            },
        },
        "required": ["method"],
    },
)


@register(_align_datum_spec, write=False)
async def run_cmm_align_datum(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    method = a.get("method")
    if not method:
        return json.dumps({"ok": False, "reason": "method is required"})

    if method == "3-2-1":
        pri = a.get("primary_pts")
        sec = a.get("secondary_pts")
        ter = a.get("tertiary_pts")
        if not pri:
            return json.dumps({"ok": False, "reason": "primary_pts required for 3-2-1"})
        if not sec:
            return json.dumps({"ok": False, "reason": "secondary_pts required for 3-2-1"})
        if not ter:
            return json.dumps({"ok": False, "reason": "tertiary_pts required for 3-2-1"})
        result = align_321(pri, sec, ter)
    elif method == "best-fit":
        nom = a.get("nominal_pts")
        meas = a.get("measured_pts")
        if not nom:
            return json.dumps({"ok": False, "reason": "nominal_pts required for best-fit"})
        if not meas:
            return json.dumps({"ok": False, "reason": "measured_pts required for best-fit"})
        result = align_bestfit(nom, meas)
    else:
        return json.dumps({"ok": False, "reason": f"unknown method: {method}"})

    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_eval_gdt
# ---------------------------------------------------------------------------

_eval_gdt_spec = ToolSpec(
    name="cmm_eval_gdt",
    description=(
        "Evaluate a GD&T characteristic directly from measured point clouds.\n"
        "\n"
        "Supported characteristics:\n"
        "  'flatness'          — surface flatness zone (ISO 1101 §12.3).\n"
        "  'circularity'       — roundness of a circular feature.\n"
        "  'cylindricity'      — cylindricity zone.\n"
        "  'perpendicularity'  — perpendicularity zone relative to datum_normal.\n"
        "  'parallelism'       — parallelism zone relative to datum_normal.\n"
        "  'angularity'        — angularity at nominal_angle_deg to datum_normal.\n"
        "\n"
        "Set tolerance to compare against the drawing callout value.\n"
        "out-of-tolerance flagged in 'warnings'.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "characteristic": {
                "type": "string",
                "enum": [
                    "flatness", "circularity", "cylindricity",
                    "perpendicularity", "parallelism", "angularity",
                ],
                "description": "GD&T characteristic to evaluate.",
            },
            "points": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Measured [x, y, z] points on the feature.",
                "minItems": 2,
            },
            "tolerance": {
                "type": "number",
                "description": "Drawing tolerance value (same units as points).  Optional.",
            },
            "datum_normal": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "[nx, ny, nz] datum plane normal; required for "
                    "perpendicularity, parallelism, angularity."
                ),
            },
            "plane_normal": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[nx, ny, nz] for circularity measurement plane.  Optional.",
            },
            "axis_guess": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[dx, dy, dz] initial axis guess for cylindricity.  Optional.",
            },
            "nominal_angle_deg": {
                "type": "number",
                "description": "Nominal angle (degrees) for angularity characteristic.",
            },
        },
        "required": ["characteristic", "points"],
    },
)


@register(_eval_gdt_spec, write=False)
async def run_cmm_eval_gdt(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    char_ = a.get("characteristic")
    points = a.get("points")
    if not char_:
        return json.dumps({"ok": False, "reason": "characteristic is required"})
    if not points:
        return json.dumps({"ok": False, "reason": "points is required"})

    tol = a.get("tolerance")
    dn = a.get("datum_normal")
    pn = a.get("plane_normal")
    ag = a.get("axis_guess")
    nom_ang = a.get("nominal_angle_deg")

    if char_ == "flatness":
        result = eval_flatness(points, tol)
    elif char_ == "circularity":
        result = eval_circularity(points, pn, tol)
    elif char_ == "cylindricity":
        result = eval_cylindricity(points, ag, tol)
    elif char_ == "perpendicularity":
        if not dn:
            return json.dumps({"ok": False, "reason": "datum_normal required for perpendicularity"})
        result = eval_perpendicularity(points, dn, tol)
    elif char_ == "parallelism":
        if not dn:
            return json.dumps({"ok": False, "reason": "datum_normal required for parallelism"})
        result = eval_parallelism(points, dn, tol)
    elif char_ == "angularity":
        if not dn:
            return json.dumps({"ok": False, "reason": "datum_normal required for angularity"})
        if nom_ang is None:
            return json.dumps({"ok": False, "reason": "nominal_angle_deg required for angularity"})
        result = eval_angularity(points, dn, nom_ang, tol)
    else:
        return json.dumps({"ok": False, "reason": f"unknown characteristic: {char_}"})

    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_eval_position
# ---------------------------------------------------------------------------

_eval_position_spec = ToolSpec(
    name="cmm_eval_position",
    description=(
        "Evaluate true-position GD&T characteristic per ASME Y14.5-2018 §8.\n"
        "\n"
        "Positional deviation = 2 × distance from measured_center to true_position "
        "(diametral tolerance zone).\n"
        "\n"
        "MMC bonus: when actual_size and mmc_size are provided the bonus tolerance "
        "= |actual_size − mmc_size| is added to the stated tolerance.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "measured_center": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x, y, z] of measured feature axis/centre point.",
            },
            "true_position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x, y, z] nominal true-position.",
            },
            "tolerance": {
                "type": "number",
                "description": "Positional tolerance (diametral zone) at MMC or RFS.",
            },
            "mmc_size": {
                "type": "number",
                "description": "Feature size at Maximum Material Condition (MMC).  Optional.",
            },
            "actual_size": {
                "type": "number",
                "description": "Actual measured feature size.  Required if mmc_size provided.",
            },
        },
        "required": ["measured_center", "true_position", "tolerance"],
    },
)


@register(_eval_position_spec, write=False)
async def run_cmm_eval_position(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    mc = a.get("measured_center")
    tp = a.get("true_position")
    tol = a.get("tolerance")
    if mc is None:
        return json.dumps({"ok": False, "reason": "measured_center is required"})
    if tp is None:
        return json.dumps({"ok": False, "reason": "true_position is required"})
    if tol is None:
        return json.dumps({"ok": False, "reason": "tolerance is required"})

    kwargs: dict = {}
    if "mmc_size" in a:
        kwargs["mmc_size"] = a["mmc_size"]
    if "actual_size" in a:
        kwargs["actual_size"] = a["actual_size"]

    result = eval_position(mc, tp, tol, **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_eval_profile
# ---------------------------------------------------------------------------

_eval_profile_spec = ToolSpec(
    name="cmm_eval_profile",
    description=(
        "Evaluate surface profile GD&T (profile of a surface, ISO 1101 §17).\n"
        "\n"
        "For each measured point the signed deviation to the nearest nominal "
        "point is computed.  Profile value = bilateral zone = "
        "2 × max(|deviation|).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "measured_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Measured surface points [x, y, z].",
                "minItems": 1,
            },
            "nominal_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Nominal CAD surface points [x, y, z].",
                "minItems": 1,
            },
            "tolerance": {
                "type": "number",
                "description": "Profile tolerance (bilateral zone).  Optional.",
            },
        },
        "required": ["measured_pts", "nominal_pts"],
    },
)


@register(_eval_profile_spec, write=False)
async def run_cmm_eval_profile(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    meas = a.get("measured_pts")
    nom = a.get("nominal_pts")
    if not meas:
        return json.dumps({"ok": False, "reason": "measured_pts is required"})
    if not nom:
        return json.dumps({"ok": False, "reason": "nominal_pts is required"})

    tol = a.get("tolerance")
    result = eval_profile(meas, nom, tol)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_gum_uncertainty
# ---------------------------------------------------------------------------

_gum_uncertainty_spec = ToolSpec(
    name="cmm_gum_uncertainty",
    description=(
        "Combine measurement uncertainty components per GUM "
        "(JCGM 100:2008).\n"
        "\n"
        "type_a  — list of standard uncertainties estimated from repeated "
        "measurements (statistical method).\n"
        "type_b  — list of standard uncertainties estimated from other means "
        "(calibration data, specs, experience).  Pre-divide half-widths by "
        "√3 (rectangular) or √6 (triangular) before passing.\n"
        "\n"
        "uc = √(Σ uᵢ²)   combined standard uncertainty.\n"
        "U  = k × uc     expanded uncertainty (default k=2, ≈95% normal).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "type_a": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Type-A standard uncertainties.",
            },
            "type_b": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Type-B standard uncertainties.",
            },
            "coverage_factor": {
                "type": "number",
                "description": "k factor (default 2.0 ≈ 95% for normal distribution).",
            },
        },
        "required": [],
    },
)


@register(_gum_uncertainty_spec, write=False)
async def run_cmm_gum_uncertainty(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    type_a = a.get("type_a", [])
    type_b = a.get("type_b", [])
    k = a.get("coverage_factor", 2.0)

    if not type_a and not type_b:
        return json.dumps({"ok": False, "reason": "at least one of type_a or type_b must be non-empty"})

    result = gum_uncertainty(type_a, type_b, k)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_probe_compensate
# ---------------------------------------------------------------------------

_probe_compensate_spec = ToolSpec(
    name="cmm_probe_compensate",
    description=(
        "Compensate raw CMM hit points for stylus-tip (probe) radius.\n"
        "\n"
        "Each measured_pt is offset by −probe_radius along its surface_normal "
        "(outward normal) to recover the actual surface point.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "measured_pts": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Raw CMM hit points [x, y, z].",
                "minItems": 1,
            },
            "surface_normals": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "Outward surface normals at each hit point [nx, ny, nz].",
                "minItems": 1,
            },
            "probe_radius": {
                "type": "number",
                "description": "Stylus-tip radius (mm or same units as points).  Must be >= 0.",
            },
        },
        "required": ["measured_pts", "surface_normals", "probe_radius"],
    },
)


@register(_probe_compensate_spec, write=False)
async def run_cmm_probe_compensate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    meas = a.get("measured_pts")
    nrms = a.get("surface_normals")
    pr = a.get("probe_radius")
    if meas is None:
        return json.dumps({"ok": False, "reason": "measured_pts is required"})
    if nrms is None:
        return json.dumps({"ok": False, "reason": "surface_normals is required"})
    if pr is None:
        return json.dumps({"ok": False, "reason": "probe_radius is required"})

    result = probe_compensate(meas, nrms, pr)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_recommend_samples
# ---------------------------------------------------------------------------

_recommend_samples_spec = ToolSpec(
    name="cmm_recommend_samples",
    description=(
        "Recommend the number of CMM measurement points based on the Nyquist "
        "criterion for the expected harmonic form error.\n"
        "\n"
        "N_nyquist = 2 × expected_harmonics.\n"
        "N_recommended = ceil(N_nyquist × safety_factor)  "
        "(default safety_factor = 2.5 per ISO/TS 12781-2 guidance).\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "expected_harmonics": {
                "type": "integer",
                "description": (
                    "Highest harmonic number expected in the form error "
                    "(e.g. 3 for tri-lobing, 15 for fine waviness).  Minimum 1."
                ),
            },
            "safety_factor": {
                "type": "number",
                "description": "Multiplier above Nyquist minimum (default 2.5).",
            },
        },
        "required": ["expected_harmonics"],
    },
)


@register(_recommend_samples_spec, write=False)
async def run_cmm_recommend_samples(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    eh = a.get("expected_harmonics")
    if eh is None:
        return json.dumps({"ok": False, "reason": "expected_harmonics is required"})

    kwargs: dict = {}
    if "safety_factor" in a:
        kwargs["safety_factor"] = a["safety_factor"]

    result = recommend_samples(eh, **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_gauge_rr
# ---------------------------------------------------------------------------

_gauge_rr_spec = ToolSpec(
    name="cmm_gauge_rr",
    description=(
        "Gauge Repeatability & Reproducibility (R&R) study per "
        "AIAG MSA 4th edition.\n"
        "\n"
        "Two methods:\n"
        "  'anova'      — Full ANOVA decomposition; more accurate.\n"
        "  'avg-range'  — Average-Range method; simpler, widely used.\n"
        "\n"
        "data is a 3-D array [part][operator][replicate].  All sub-arrays "
        "must have the same length.\n"
        "\n"
        "Key outputs:\n"
        "  EV            — Repeatability (Equipment Variation).\n"
        "  AV            — Reproducibility (Appraiser Variation).\n"
        "  GRR           — Combined Gauge R&R (5.15σ study variation).\n"
        "  PV            — Part Variation.\n"
        "  TV            — Total Variation.\n"
        "  pct_study_var — GRR as % of total study variation (<10% good, "
        ">30% not capable).\n"
        "  ndc           — Number of Distinct Categories (≥5 acceptable).\n"
        "\n"
        "Warnings flagged when pct_study_var > 10% or ndc < 5.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["anova", "avg-range"],
                "description": "R&R analysis method.",
            },
            "data": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                },
                "description": (
                    "3-D data array [part][operator][replicate].  "
                    "Example: 10 parts × 3 operators × 2 replicates."
                ),
            },
            "usl": {
                "type": "number",
                "description": "Upper spec limit (optional; enables %tolerance output).",
            },
            "lsl": {
                "type": "number",
                "description": "Lower spec limit (optional; enables %tolerance output).",
            },
        },
        "required": ["method", "data"],
    },
)


@register(_gauge_rr_spec, write=False)
async def run_cmm_gauge_rr(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    method = a.get("method")
    data = a.get("data")
    if not method:
        return json.dumps({"ok": False, "reason": "method is required"})
    if data is None:
        return json.dumps({"ok": False, "reason": "data is required"})

    kwargs: dict = {}
    if "usl" in a:
        kwargs["usl"] = a["usl"]
    if "lsl" in a:
        kwargs["lsl"] = a["lsl"]

    if method == "anova":
        result = gauge_rr_anova(data, **kwargs)
    elif method == "avg-range":
        result = gauge_rr_avgrange(data, **kwargs)
    else:
        return json.dumps({"ok": False, "reason": f"unknown method: {method}"})

    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: cmm_process_capability
# ---------------------------------------------------------------------------

_process_capability_spec = ToolSpec(
    name="cmm_process_capability",
    description=(
        "Compute process capability indices Cpk and Ppk from a sample of "
        "CMM measurements.\n"
        "\n"
        "Cpk  uses within-subgroup sigma (moving-range method) — short-term "
        "capability.\n"
        "Ppk  uses overall sample sigma — long-term performance.\n"
        "\n"
        "AIAG / AISC convention: Cpk ≥ 1.33 (four-sigma) is capable; "
        "1.0 ≤ Cpk < 1.33 is marginal; Cpk < 1.0 is not capable.\n"
        "\n"
        "Warnings flagged when Cpk < 1.33 or out-of-spec measurements exist.\n"
        "\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "measurements": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Sample of measured values (e.g. diameter in mm).",
                "minItems": 2,
            },
            "usl": {
                "type": "number",
                "description": "Upper specification limit.",
            },
            "lsl": {
                "type": "number",
                "description": "Lower specification limit.",
            },
        },
        "required": ["measurements", "usl", "lsl"],
    },
)


@register(_process_capability_spec, write=False)
async def run_cmm_process_capability(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    meas = a.get("measurements")
    usl = a.get("usl")
    lsl = a.get("lsl")
    if meas is None:
        return json.dumps({"ok": False, "reason": "measurements is required"})
    if usl is None:
        return json.dumps({"ok": False, "reason": "usl is required"})
    if lsl is None:
        return json.dumps({"ok": False, "reason": "lsl is required"})

    result = process_capability(meas, usl, lsl)
    return ok_payload(result) if result.get("ok") else json.dumps(result)
