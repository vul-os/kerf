"""tools.py — LLM tool surface for kerf-hvac.

Registers the following tools:
  - hvac.size_duct            — Select duct size for given airflow and velocity.
  - hvac.pressure_drop        — Compute pressure drop for a straight duct run.
  - hvac.fitting_loss         — Compute minor loss for a fitting.
  - hvac.reducer_flat_pattern — Generate reducer flat-pattern dimensions.
  - hvac.elbow_flat_pattern   — Generate elbow flat-pattern dimensions.
"""

from __future__ import annotations

import json
import math
from typing import Any

from kerf_hvac.duct import DuctShape, cfm_to_m3s, fpm_to_ms, m3s_to_cfm, ms_to_fpm
from kerf_hvac.sizing import size_duct
from kerf_hvac.pressure import (
    darcy_weisbach_loss,
    minor_loss,
    total_duct_loss,
    fitting_pressure_loss,
    compute_duct_run_pressure_drop,
    ELBOW_90_RECT_K,
    ELBOW_90_ROUND_K,
    ELBOW_45_RECT_K,
    TEE_MAIN_K,
    TEE_BRANCH_K,
    REDUCER_K,
    CAP_K,
    FLEX_PER_METRE_K,
    FITTING_KINDS,
)
from kerf_hvac.flat_pattern import rect_elbow_pattern, rect_reducer_pattern


# ---------------------------------------------------------------------------
# Tool registry shim (mirrors kerf_wiring._compat pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, ok_payload, err_payload, register  # type: ignore
except ImportError:
    from kerf_hvac._compat import ToolSpec, ok_payload, err_payload, register  # type: ignore


# ---------------------------------------------------------------------------
# FITTING K LOOKUP TABLE
# ---------------------------------------------------------------------------

_FITTING_K: dict[str, float] = {
    "elbow_90_rect": ELBOW_90_RECT_K,
    "elbow_90_round": ELBOW_90_ROUND_K,
    "elbow_45_rect": ELBOW_45_RECT_K,
    "tee_main": TEE_MAIN_K,
    "tee_branch": TEE_BRANCH_K,
    "reducer": REDUCER_K,
    "cap": CAP_K,
    "flex_per_metre": FLEX_PER_METRE_K,
}


# ---------------------------------------------------------------------------
# hvac.size_duct
# ---------------------------------------------------------------------------

_size_duct_spec = ToolSpec(
    name="hvac.size_duct",
    description=(
        "Select the smallest standard rectangular or round duct size that "
        "satisfies the given airflow at the maximum allowable velocity. "
        "Returns width, height (rectangular) or diameter (round) in mm, "
        "actual velocity, and hydraulic diameter."
    ),
    input_schema={
        "type": "object",
        "required": ["airflow_cfm", "max_velocity_fpm"],
        "properties": {
            "airflow_cfm": {
                "type": "number",
                "description": "Design airflow in CFM.",
            },
            "max_velocity_fpm": {
                "type": "number",
                "description": "Maximum allowable duct velocity in FPM. "
                               "Typical supply trunk: 1200–2500 FPM; "
                               "return air: 600–1500 FPM.",
            },
            "shape": {
                "type": "string",
                "enum": ["rectangular", "round"],
                "description": "Duct cross-section shape (default: rectangular).",
                "default": "rectangular",
            },
            "max_aspect_ratio": {
                "type": "number",
                "description": "Maximum width:height ratio for rectangular ducts "
                               "(default 4.0 per ASHRAE).",
                "default": 4.0,
            },
            "preferred_height_mm": {
                "type": "number",
                "description": "Fix the duct height (mm) and solve only for "
                               "width. Useful for ceiling plenum constraints.",
            },
        },
    },
)


@register(_size_duct_spec)
def handle_size_duct(args: dict) -> str:
    try:
        q_cfm = float(args["airflow_cfm"])
        v_fpm = float(args["max_velocity_fpm"])
        shape_str = args.get("shape", "rectangular")
        shape = DuctShape(shape_str)
        max_ar = float(args.get("max_aspect_ratio", 4.0))
        pref_h = args.get("preferred_height_mm")
        if pref_h is not None:
            pref_h = float(pref_h)

        result = size_duct(
            airflow_m3s=cfm_to_m3s(q_cfm),
            max_velocity_m_s=fpm_to_ms(v_fpm),
            shape=shape,
            max_aspect_ratio=max_ar,
            preferred_height_mm=pref_h,
        )

        return ok_payload({
            "shape": result.shape.value,
            "width_mm": result.width_mm,
            "height_mm": result.height_mm,
            "diameter_mm": result.diameter_mm,
            "actual_velocity_fpm": round(ms_to_fpm(result.actual_velocity_m_s), 1),
            "actual_velocity_m_s": round(result.actual_velocity_m_s, 3),
            "area_m2": round(result.area_m2, 6),
            "hydraulic_diameter_mm": round(result.hydraulic_diameter_m * 1000, 1),
            "aspect_ratio": result.aspect_ratio,
        })
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# hvac.pressure_drop
# ---------------------------------------------------------------------------

_pressure_drop_spec = ToolSpec(
    name="hvac.pressure_drop",
    description=(
        "Compute the Darcy-Weisbach pressure drop (Pa) for a straight duct run "
        "plus optional fitting losses. Returns friction, fitting, and total losses."
    ),
    input_schema={
        "type": "object",
        "required": ["velocity_m_s", "hydraulic_diameter_mm", "length_m"],
        "properties": {
            "velocity_m_s": {
                "type": "number",
                "description": "Mean air velocity in m/s.",
            },
            "hydraulic_diameter_mm": {
                "type": "number",
                "description": "Hydraulic diameter D_h in mm.",
            },
            "length_m": {
                "type": "number",
                "description": "Duct run length in metres.",
            },
            "roughness_mm": {
                "type": "number",
                "description": "Absolute roughness ε in mm (default 0.09 for galvanised steel).",
                "default": 0.09,
            },
            "fittings": {
                "type": "array",
                "description": "List of fitting type strings for minor losses, e.g. ['elbow_90_rect'].",
                "items": {"type": "string"},
            },
        },
    },
)


@register(_pressure_drop_spec)
def handle_pressure_drop(args: dict) -> str:
    try:
        v = float(args["velocity_m_s"])
        dh_mm = float(args["hydraulic_diameter_mm"])
        L = float(args["length_m"])
        eps_mm = float(args.get("roughness_mm", 0.09))
        fittings_list = args.get("fittings", [])

        k_list = []
        unknown = []
        for ft in fittings_list:
            if ft in _FITTING_K:
                k_list.append(_FITTING_K[ft])
            else:
                unknown.append(ft)

        result = total_duct_loss(
            velocity_m_s=v,
            hydraulic_diameter_m=dh_mm / 1000,
            length_m=L,
            fittings_k=k_list,
            roughness_m=eps_mm / 1000,
        )

        out = {
            "friction_pa": round(result["friction_pa"], 4),
            "fittings_pa": round(result["fittings_pa"], 4),
            "total_pa": round(result["total_pa"], 4),
            "velocity_pressure_pa": round(result["velocity_pressure_pa"], 4),
            "friction_factor": round(result["friction_factor"], 6),
            "reynolds_number": round(
                1.204 * v * (dh_mm / 1000) / 1.81e-5, 0
            ),
        }
        if unknown:
            out["warning"] = f"Unknown fitting types ignored: {unknown}"
        return ok_payload(out)
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# hvac.fitting_loss
# ---------------------------------------------------------------------------

_fitting_loss_spec = ToolSpec(
    name="hvac.fitting_loss",
    description=(
        "Compute the minor pressure loss (Pa) for a duct fitting given its "
        "approach velocity and K coefficient."
    ),
    input_schema={
        "type": "object",
        "required": ["velocity_m_s", "fitting_type"],
        "properties": {
            "velocity_m_s": {
                "type": "number",
                "description": "Approach velocity in m/s.",
            },
            "fitting_type": {
                "type": "string",
                "enum": list(_FITTING_K.keys()),
                "description": "ASHRAE fitting type identifier.",
            },
        },
    },
)


@register(_fitting_loss_spec)
def handle_fitting_loss(args: dict) -> str:
    try:
        v = float(args["velocity_m_s"])
        ft = args["fitting_type"]
        if ft not in _FITTING_K:
            return err_payload(f"Unknown fitting type: {ft!r}", "BAD_ARGS")
        k = _FITTING_K[ft]
        loss = minor_loss(v, k)
        return ok_payload({
            "fitting_type": ft,
            "k_coefficient": k,
            "velocity_m_s": v,
            "loss_pa": round(loss, 4),
        })
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# hvac.reducer_flat_pattern
# ---------------------------------------------------------------------------

_reducer_pattern_spec = ToolSpec(
    name="hvac.reducer_flat_pattern",
    description=(
        "Generate flat-pattern dimensions for a rectangular duct reducer "
        "(concentric taper). Returns the trapezoidal panel shapes and slant lengths."
    ),
    input_schema={
        "type": "object",
        "required": [
            "width_upstream_mm", "height_upstream_mm",
            "width_downstream_mm", "height_downstream_mm",
            "axial_length_mm",
        ],
        "properties": {
            "width_upstream_mm": {"type": "number", "description": "Upstream duct width (mm)."},
            "height_upstream_mm": {"type": "number", "description": "Upstream duct height (mm)."},
            "width_downstream_mm": {"type": "number", "description": "Downstream duct width (mm)."},
            "height_downstream_mm": {"type": "number", "description": "Downstream duct height (mm)."},
            "axial_length_mm": {"type": "number", "description": "Axial run length of reducer (mm)."},
        },
    },
)


@register(_reducer_pattern_spec)
def handle_reducer_flat_pattern(args: dict) -> str:
    try:
        pat = rect_reducer_pattern(
            width_upstream_mm=float(args["width_upstream_mm"]),
            height_upstream_mm=float(args["height_upstream_mm"]),
            width_downstream_mm=float(args["width_downstream_mm"]),
            height_downstream_mm=float(args["height_downstream_mm"]),
            axial_length_mm=float(args["axial_length_mm"]),
        )
        return ok_payload({
            "top_plate": pat.top_plate,
            "bottom_plate": pat.bottom_plate,
            "left_plate": pat.left_plate,
            "right_plate": pat.right_plate,
            "top_slant_length_mm": round(pat.top_slant_length_mm, 3),
            "side_slant_length_mm": round(pat.side_slant_length_mm, 3),
            "axial_length_mm": pat.axial_length_mm,
        })
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# hvac.elbow_flat_pattern
# ---------------------------------------------------------------------------

_elbow_pattern_spec = ToolSpec(
    name="hvac.elbow_flat_pattern",
    description=(
        "Generate flat-pattern dimensions for a rectangular radius duct elbow. "
        "Returns throat plate, heel plate, and two cheek panel polygons, plus "
        "arc lengths for all faces."
    ),
    input_schema={
        "type": "object",
        "required": ["width_mm", "height_mm"],
        "properties": {
            "width_mm": {
                "type": "number",
                "description": "Duct width (dimension across the bend, mm).",
            },
            "height_mm": {
                "type": "number",
                "description": "Duct height in the bend plane (mm).",
            },
            "angle_deg": {
                "type": "number",
                "description": "Turn angle in degrees (default 90).",
                "default": 90.0,
            },
            "throat_radius_mm": {
                "type": "number",
                "description": "Bend radius at the throat (inner face) in mm. "
                               "Defaults to 1× duct height.",
            },
        },
    },
)


@register(_elbow_pattern_spec)
def handle_elbow_flat_pattern(args: dict) -> str:
    try:
        w = float(args["width_mm"])
        h = float(args["height_mm"])
        angle = float(args.get("angle_deg", 90.0))
        tr = args.get("throat_radius_mm")
        if tr is not None:
            tr = float(tr)

        pat = rect_elbow_pattern(w, h, angle, tr)
        return ok_payload({
            "throat_plate": pat.throat_plate,
            "heel_plate": pat.heel_plate,
            "cheek_left": pat.cheek_left,
            "cheek_right": pat.cheek_right,
            "throat_arc_length_mm": round(pat.throat_arc_length_mm, 3),
            "heel_arc_length_mm": round(pat.heel_arc_length_mm, 3),
            "centre_arc_length_mm": round(pat.centre_arc_length_mm, 3),
            "angle_deg": pat.angle_deg,
            "throat_radius_mm": pat.throat_radius_mm,
        })
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# hvac.fitting_pressure_loss  — ASHRAE §35 Table 21-1 fitting loss
# ---------------------------------------------------------------------------

_fitting_pressure_loss_spec = ToolSpec(
    name="hvac.fitting_pressure_loss",
    description=(
        "Compute the pressure loss (Pa) across a specific duct fitting using "
        "ASHRAE Handbook of Fundamentals 2021 §35 (Chapter 21) Table 21-1 "
        "C coefficients.  Supports 10 fitting kinds: elbows, tees, transitions, "
        "dampers, reducers, and expanders.  "
        "DISCLAIMER: Values from ASHRAE HOF 2021 §35 — NOT ASHRAE certified."
    ),
    input_schema={
        "type": "object",
        "required": ["fitting_kind", "flow_rate_cfm"],
        "properties": {
            "fitting_kind": {
                "type": "string",
                "enum": sorted(FITTING_KINDS),
                "description": (
                    "ASHRAE §35 fitting type.  One of: "
                    "elbow_90_smooth, elbow_90_segmented, elbow_45, "
                    "tee_branch, tee_through, transition_gradual, "
                    "transition_abrupt, damper_butterfly, "
                    "reducer_gradual, expander_gradual."
                ),
            },
            "flow_rate_cfm": {
                "type": "number",
                "description": "Volumetric airflow in CFM.",
            },
            "diameter_m": {
                "type": "number",
                "description": "Upstream duct inner diameter in metres (round duct).",
            },
            "width_m": {
                "type": "number",
                "description": "Upstream duct width in metres (rectangular duct).",
            },
            "height_m": {
                "type": "number",
                "description": "Upstream duct height in metres (rectangular duct).",
            },
            "area_m2": {
                "type": "number",
                "description": "Upstream duct cross-sectional area in m² (alternative to diameter/width+height).",
            },
            "r_over_d": {
                "type": "number",
                "description": "Centreline bend radius / duct diameter for smooth elbows. Default 1.0.",
                "default": 1.0,
            },
            "n_segments": {
                "type": "integer",
                "description": "Number of gore segments for segmented elbows (2–5). Default 4.",
                "default": 4,
            },
            "A2_over_A1": {
                "type": "number",
                "description": "Downstream/upstream area ratio for abrupt contraction (0–1).",
            },
            "A1_over_A2": {
                "type": "number",
                "description": "Upstream/downstream area ratio for gradual expander (0–1).",
            },
            "theta_half_deg": {
                "type": "number",
                "description": "Half included-angle of taper in degrees for gradual reducer/transition. Default 10.",
                "default": 10.0,
            },
            "Ab_over_Ac": {
                "type": "number",
                "description": "Branch/common area ratio for tee fittings (0–1). Default 0.5.",
                "default": 0.5,
            },
            "blade_angle_deg": {
                "type": "number",
                "description": "Damper blade opening angle in degrees (10–90). Default 90 (wide open).",
                "default": 90.0,
            },
        },
    },
)


@register(_fitting_pressure_loss_spec)
def handle_fitting_pressure_loss(args: dict) -> str:
    try:
        fk = args["fitting_kind"]
        q_cfm = float(args["flow_rate_cfm"])

        # Build params dict from optional geometric fields
        params: dict = {}
        for key in (
            "diameter_m", "width_m", "height_m", "area_m2",
            "r_over_d", "n_segments", "A2_over_A1", "A1_over_A2",
            "theta_half_deg", "Ab_over_Ac", "blade_angle_deg",
        ):
            if key in args and args[key] is not None:
                params[key] = float(args[key]) if key != "n_segments" else int(args[key])

        loss_pa = fitting_pressure_loss(fk, params, q_cfm)

        return ok_payload({
            "fitting_kind": fk,
            "flow_rate_cfm": q_cfm,
            "loss_pa": round(loss_pa, 4),
            "disclaimer": (
                "Values from ASHRAE Handbook of Fundamentals 2021 §35 — "
                "NOT ASHRAE certified."
            ),
        })
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# hvac.compute_run_pressure_drop  — end-to-end duct run solver
# ---------------------------------------------------------------------------

_compute_run_spec = ToolSpec(
    name="hvac.compute_run_pressure_drop",
    description=(
        "Compute total pressure drop (Pa) for a multi-segment duct run "
        "including straight-duct friction losses (Darcy-Weisbach / Colebrook-White) "
        "and fitting losses (ASHRAE HOF 2021 §35 Table 21-1).  "
        "Returns per-segment and per-fitting breakdowns.  "
        "DISCLAIMER: Values from ASHRAE HOF 2021 §35 — NOT ASHRAE certified."
    ),
    input_schema={
        "type": "object",
        "required": ["duct_segments", "fittings", "flow_cfm"],
        "properties": {
            "duct_segments": {
                "type": "array",
                "description": (
                    "List of straight-duct segments.  Each object requires "
                    "'length_m' and either 'diameter_m' (round) or "
                    "'width_m'+'height_m' (rectangular).  Optional: 'roughness_m'."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "length_m": {"type": "number"},
                        "diameter_m": {"type": "number"},
                        "width_m": {"type": "number"},
                        "height_m": {"type": "number"},
                        "roughness_m": {"type": "number"},
                    },
                },
            },
            "fittings": {
                "type": "array",
                "description": (
                    "List of fittings.  Each object requires 'fitting_kind' "
                    "(one of the ASHRAE §35 kinds) and 'params' (geometric "
                    "parameter dict — same keys as hvac.fitting_pressure_loss)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "fitting_kind": {"type": "string"},
                        "params": {"type": "object"},
                    },
                },
            },
            "flow_cfm": {
                "type": "number",
                "description": "Total volumetric airflow in CFM.",
            },
            "roughness_mm": {
                "type": "number",
                "description": "Default absolute roughness in mm for all segments (default 0.09 galvanised steel).",
                "default": 0.09,
            },
        },
    },
)


@register(_compute_run_spec)
def handle_compute_run_pressure_drop(args: dict) -> str:
    try:
        segs = args["duct_segments"]
        fits = args["fittings"]
        q_cfm = float(args["flow_cfm"])
        eps_mm = float(args.get("roughness_mm", 0.09))

        result = compute_duct_run_pressure_drop(
            duct_segments=segs,
            fittings=fits,
            flow_cfm=q_cfm,
            roughness_m=eps_mm / 1000.0,
        )

        return ok_payload({
            "straight_duct_pa": round(result["straight_duct_pa"], 4),
            "fittings_pa": round(result["fittings_pa"], 4),
            "total_pa": round(result["total_pa"], 4),
            "flow_cfm": result["flow_cfm"],
            "segment_losses_pa": [round(x, 4) for x in result["segment_losses_pa"]],
            "fitting_losses_pa": [round(x, 4) for x in result["fitting_losses_pa"]],
            "disclaimer": (
                "Values from ASHRAE Handbook of Fundamentals 2021 §35 — "
                "NOT ASHRAE certified."
            ),
        })
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# TOOLS list (for plugin registration)
# ---------------------------------------------------------------------------

TOOLS = [
    ("hvac.size_duct", _size_duct_spec, handle_size_duct),
    ("hvac.pressure_drop", _pressure_drop_spec, handle_pressure_drop),
    ("hvac.fitting_loss", _fitting_loss_spec, handle_fitting_loss),
    ("hvac.reducer_flat_pattern", _reducer_pattern_spec, handle_reducer_flat_pattern),
    ("hvac.elbow_flat_pattern", _elbow_pattern_spec, handle_elbow_flat_pattern),
    ("hvac.fitting_pressure_loss", _fitting_pressure_loss_spec, handle_fitting_pressure_loss),
    ("hvac.compute_run_pressure_drop", _compute_run_spec, handle_compute_run_pressure_drop),
]
