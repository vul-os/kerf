"""tools.py — LLM tool surface for kerf-hvac.

Registers the following tools:
  - hvac.size_duct            — Select duct size for given airflow and velocity.
  - hvac.pressure_drop        — Compute pressure drop for a straight duct run.
  - hvac.fitting_loss         — Compute minor loss for a fitting.
  - hvac.reducer_flat_pattern — Generate reducer flat-pattern dimensions.
  - hvac.elbow_flat_pattern   — Generate elbow flat-pattern dimensions.
  - hvac.equipment_select     — Select AHRI-listed equipment by category and capacity.
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
    ELBOW_90_RECT_K,
    ELBOW_90_ROUND_K,
    ELBOW_45_RECT_K,
    TEE_MAIN_K,
    TEE_BRANCH_K,
    REDUCER_K,
    CAP_K,
    FLEX_PER_METRE_K,
)
from kerf_hvac.flat_pattern import rect_elbow_pattern, rect_reducer_pattern
from kerf_hvac.ahri_catalogue import lookup_equipment, VALID_CATEGORIES


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
# hvac.equipment_select  (AHRI-listed equipment catalogue)
# ---------------------------------------------------------------------------

_equipment_select_spec = ToolSpec(
    name="hvac.equipment_select",
    description=(
        "Select AHRI-certified HVAC equipment that matches the given category "
        "and design capacity.  Returns up to 5 matching models from the "
        "built-in AHRI-listed catalogue, each with manufacturer, AHRI "
        "certification number, full-load efficiency (EER / COP / AFUE), and "
        "certified part-load curve values at 25 %, 50 %, 75 %, and 100 % "
        "load.  Source: AHRI Certified Products Directory "
        "(https://www.ahridirectory.org).  Catalogue covers 30 representative "
        "models; not OEM-complete."
    ),
    input_schema={
        "type": "object",
        "required": ["category", "capacity_btu_hr"],
        "properties": {
            "category": {
                "type": "string",
                "enum": sorted(VALID_CATEGORIES),
                "description": (
                    "Equipment category. One of: rooftop_ac, split_ac, "
                    "water_chiller, air_chiller, gas_boiler, heat_pump."
                ),
            },
            "capacity_btu_hr": {
                "type": "number",
                "description": (
                    "Required cooling or heating capacity in BTU/hr. "
                    "Models within ±40 % of this value are returned. "
                    "Pass 0 to return all models in the category."
                ),
            },
            "min_efficiency": {
                "type": "number",
                "description": (
                    "Optional minimum efficiency gate. "
                    "For AC / chiller categories: minimum EER or cooling COP. "
                    "For gas_boiler: minimum AFUE (0–1). "
                    "For heat_pump: minimum cooling COP. "
                    "Pass null to skip."
                ),
            },
        },
    },
)


@register(_equipment_select_spec)
def handle_equipment_select(args: dict) -> str:
    try:
        category = str(args["category"])
        capacity = float(args["capacity_btu_hr"])
        min_eff = args.get("min_efficiency")
        if min_eff is not None:
            min_eff = float(min_eff)

        models = lookup_equipment(category, capacity, min_eff)

        if not models:
            return ok_payload({
                "models": [],
                "note": (
                    f"No AHRI-listed models found for category={category!r} "
                    f"near {capacity:.0f} BTU/hr. "
                    "Try widening the capacity range or removing the efficiency gate."
                ),
            })

        def _serialise(m):
            out: dict = {
                "manufacturer": m.manufacturer,
                "model_number": m.model_number,
                "ahri_number": m.ahri_number,
                "category": m.category,
                "capacity_btu_hr": m.capacity_btu_hr,
                "part_load_curve": {str(k): v for k, v in sorted(m.part_load_curve.items())},
            }
            if m.eer is not None:
                out["eer"] = m.eer
            if m.ieer is not None:
                out["ieer"] = m.ieer
            if m.cop_cooling is not None:
                out["cop_cooling"] = m.cop_cooling
            if m.cop_heating is not None:
                out["cop_heating"] = m.cop_heating
            if m.afue is not None:
                out["afue"] = m.afue
            if m.notes:
                out["notes"] = m.notes
            return out

        return ok_payload({
            "models": [_serialise(m) for m in models[:5]],
            "total_matches": len(models),
            "source": "AHRI Certified Products Directory — https://www.ahridirectory.org",
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
    ("hvac.equipment_select", _equipment_select_spec, handle_equipment_select),
]
