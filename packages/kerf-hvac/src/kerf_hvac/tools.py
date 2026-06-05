"""tools.py — LLM tool surface for kerf-hvac.

Registers the following tools:
  - hvac.size_duct                  — Select duct size for given airflow and velocity.
  - hvac.pressure_drop              — Compute pressure drop for a straight duct run.
  - hvac.fitting_loss               — Compute minor loss for a fitting.
  - hvac.reducer_flat_pattern       — Generate reducer flat-pattern dimensions.
  - hvac.elbow_flat_pattern         — Generate elbow flat-pattern dimensions.
  - hvac.equal_friction_sizing      — ASHRAE §35 equal-friction single-segment sizing.
  - hvac.size_duct_run              — ASHRAE §35 equal-friction multi-segment run sizing.
  - hvac.airside_system_model       — Full AHU air-side system model: psychrometrics,
                                      cooling/heating coils, economizer, VAV boxes, fans,
                                      coupled to water-side chiller/boiler plant.
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
from kerf_hvac.duct_sizing_optimizer import equal_friction_size, size_duct_run


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
# hvac.equal_friction_sizing
# ---------------------------------------------------------------------------

_equal_friction_sizing_spec = ToolSpec(
    name="hvac.equal_friction_sizing",
    description=(
        "Size a single round duct segment by the ASHRAE §35 equal-friction method. "
        "Given airflow and a target friction rate (in w.c. / 100 ft), returns the "
        "exact and standard-size diameters, mean velocity, and actual friction rate. "
        "Default friction rate 0.08 in w.c./100 ft (ASHRAE low-pressure default). "
        "Optionally enforces a maximum velocity (FPM) for residential noise budgets. "
        "DISCLAIMER: ASHRAE methods — NOT ASHRAE certified."
    ),
    input_schema={
        "type": "object",
        "required": ["flow_cfm"],
        "properties": {
            "flow_cfm": {
                "type": "number",
                "description": "Design airflow through this segment (CFM).",
            },
            "friction_rate_in_wc_per_100ft": {
                "type": "number",
                "description": (
                    "Target friction loss rate (in w.c. / 100 ft). "
                    "Default 0.08 (ASHRAE low-pressure supply). "
                    "Typical range: 0.06–0.12 in w.c./100 ft."
                ),
                "default": 0.08,
            },
            "roughness_mm": {
                "type": "number",
                "description": (
                    "Duct absolute roughness (mm). Default 0.09 mm (galvanised steel)."
                ),
                "default": 0.09,
            },
            "max_velocity_fpm": {
                "type": "number",
                "description": (
                    "Optional velocity ceiling (FPM). Duct will be sized up if "
                    "equal-friction diameter exceeds this. "
                    "Recommended: 700 FPM residential, 1200 FPM light commercial."
                ),
            },
        },
    },
)


@register(_equal_friction_sizing_spec)
def handle_equal_friction_sizing(args: dict) -> str:
    try:
        flow_cfm = float(args["flow_cfm"])
        fr = float(args.get("friction_rate_in_wc_per_100ft", 0.08))
        eps_mm = float(args.get("roughness_mm", 0.09))
        max_v = args.get("max_velocity_fpm")
        if max_v is not None:
            max_v = float(max_v)

        result = equal_friction_size(
            flow_cfm=flow_cfm,
            friction_rate_in_wc_per_100ft=fr,
            roughness_mm=eps_mm,
            max_velocity_fpm=max_v,
        )
        return ok_payload(result)
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# hvac.size_duct_run
# ---------------------------------------------------------------------------

_size_duct_run_spec = ToolSpec(
    name="hvac.size_duct_run",
    description=(
        "Size all segments in a duct run by the ASHRAE §35 equal-friction method "
        "(or static_regain / T_method stubs). "
        "Pass a list of segment descriptors (label, optional flow_cfm override, "
        "optional length_ft, optional downstream_cfm branch takeoff). "
        "Upstream segments automatically carry more flow than downstream segments. "
        "Returns sized diameters, velocities, and friction losses for each segment. "
        "DISCLAIMER: ASHRAE methods — NOT ASHRAE certified."
    ),
    input_schema={
        "type": "object",
        "required": ["segments", "total_flow_cfm"],
        "properties": {
            "segments": {
                "type": "array",
                "description": (
                    "Ordered list of duct segment descriptors, trunk-first. "
                    "Each item may include: label (str), flow_cfm (number, optional override), "
                    "length_ft (number, optional), downstream_cfm (number, optional branch takeoff)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "flow_cfm": {"type": "number"},
                        "length_ft": {"type": "number"},
                        "downstream_cfm": {"type": "number"},
                    },
                },
            },
            "total_flow_cfm": {
                "type": "number",
                "description": "Total system airflow entering the first segment (CFM).",
            },
            "method": {
                "type": "string",
                "enum": ["equal_friction", "static_regain", "T_method"],
                "description": "Sizing method. Only equal_friction is fully implemented.",
                "default": "equal_friction",
            },
            "friction_rate_in_wc_per_100ft": {
                "type": "number",
                "description": "Target friction rate (in w.c. / 100 ft). Default 0.08.",
                "default": 0.08,
            },
            "roughness_mm": {
                "type": "number",
                "description": "Duct roughness (mm). Default 0.09.",
                "default": 0.09,
            },
            "max_velocity_fpm": {
                "type": "number",
                "description": "Optional velocity ceiling (FPM) for all segments.",
            },
        },
    },
)


@register(_size_duct_run_spec)
def handle_size_duct_run(args: dict) -> str:
    try:
        segments = args["segments"]
        if not isinstance(segments, list):
            return err_payload("segments must be a list", "BAD_ARGS")

        total_flow = float(args["total_flow_cfm"])
        method = args.get("method", "equal_friction")
        fr = float(args.get("friction_rate_in_wc_per_100ft", 0.08))
        eps_mm = float(args.get("roughness_mm", 0.09))
        max_v = args.get("max_velocity_fpm")
        if max_v is not None:
            max_v = float(max_v)

        sized = size_duct_run(
            segments=segments,
            total_flow_cfm=total_flow,
            method=method,  # type: ignore[arg-type]
            friction_rate_in_wc_per_100ft=fr,
            roughness_mm=eps_mm,
            max_velocity_fpm=max_v,
        )

        return ok_payload([
            {
                "label": s.label,
                "flow_cfm": round(s.flow_cfm, 2),
                "length_ft": s.length_ft,
                "diameter_in": s.diameter_in,
                "diameter_mm": round(s.diameter_mm, 1),
                "velocity_fpm": s.velocity_fpm,
                "friction_loss_in_wc_per_100ft": s.friction_loss_in_wc_per_100ft,
                "total_friction_loss_in_wc": s.total_friction_loss_in_wc,
                "method": s.method,
            }
            for s in sized
        ])
    except (KeyError, ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")


# ---------------------------------------------------------------------------
# hvac.airside_system_model
# ---------------------------------------------------------------------------

_airside_system_spec = ToolSpec(
    name="hvac.airside_system_model",
    description=(
        "Full AHU (Air Handling Unit) air-side system model with proper psychrometrics. "
        "Models: supply/return fans (ΔP·Q/η), cooling coil (sensible+latent, ADP/bypass-factor), "
        "heating coil (effectiveness-NTU), economizer (OA mixing for free cooling), "
        "VAV terminal boxes (airflow modulation per zone load), duct static pressure. "
        "Couples air-side coil loads to water-side plant (chiller COP, boiler efficiency). "
        "Returns psychrometric state points (T_db, W, h, RH, T_dp, T_wb), coil loads, "
        "fan power, VAV airflows, free-cooling hours indicator, and energy balance. "
        "DISCLAIMER: Steady-state single-design-point model; ASHRAE fundamentals. NOT ASHRAE certified."
    ),
    input_schema={
        "type": "object",
        "required": ["outdoor_air", "return_air", "zones"],
        "properties": {
            "outdoor_air": {
                "type": "object",
                "description": "Outdoor air conditions.",
                "required": ["T_db_C"],
                "properties": {
                    "T_db_C": {"type": "number", "description": "Dry-bulb temperature, °C."},
                    "rh_fraction": {"type": "number", "description": "Relative humidity 0–1 (default 0.55)."},
                    "W_kg_kgda": {"type": "number", "description": "Humidity ratio kg_w/kg_da (alternative to rh_fraction)."},
                },
            },
            "return_air": {
                "type": "object",
                "description": "Return air conditions (from zones).",
                "required": ["T_db_C"],
                "properties": {
                    "T_db_C": {"type": "number", "description": "Dry-bulb temperature, °C."},
                    "rh_fraction": {"type": "number", "description": "Relative humidity 0–1 (default 0.50)."},
                    "W_kg_kgda": {"type": "number", "description": "Humidity ratio kg_w/kg_da (alternative to rh_fraction)."},
                },
            },
            "zones": {
                "type": "array",
                "description": "List of VAV-served zones.",
                "items": {
                    "type": "object",
                    "required": ["name", "design_flow_m3s", "zone_load_W"],
                    "properties": {
                        "name": {"type": "string", "description": "Zone name."},
                        "design_flow_m3s": {"type": "number", "description": "Design airflow to zone, m³/s."},
                        "zone_load_W": {"type": "number", "description": "Zone sensible cooling load, W (+ve = cooling required)."},
                        "zone_T_setpoint_C": {"type": "number", "description": "Zone thermostat setpoint, °C (default 22)."},
                        "zone_T_current_C": {"type": "number", "description": "Current zone temperature, °C (default = setpoint + 2)."},
                        "min_flow_fraction": {"type": "number", "description": "VAV minimum airflow fraction 0–1 (default 0.25)."},
                    },
                },
            },
            "ahu": {
                "type": "object",
                "description": "AHU configuration overrides.",
                "properties": {
                    "name": {"type": "string", "description": "AHU identifier (default 'AHU-1')."},
                    "supply_airflow_m3s": {"type": "number", "description": "Design supply airflow, m³/s. Auto-computed from zones if omitted."},
                    "min_oa_fraction": {"type": "number", "description": "Minimum OA fraction (default 0.15)."},
                    "economizer_setpoint_C": {"type": "number", "description": "Economizer dry-bulb lockout temp, °C (default 18)."},
                    "enable_economizer": {"type": "boolean", "description": "Enable economizer (default true)."},
                    "chw_supply_T_C": {"type": "number", "description": "Chilled-water supply temp, °C (default 7)."},
                    "chw_return_T_C": {"type": "number", "description": "Chilled-water return temp, °C (default 12)."},
                    "cooling_coil_bypass_factor": {"type": "number", "description": "Coil bypass factor BF 0–1 (default 0.10)."},
                    "hw_supply_T_C": {"type": "number", "description": "Hot-water supply temp, °C (default 60)."},
                    "supply_fan_efficiency": {"type": "number", "description": "Supply fan mechanical efficiency (default 0.70)."},
                    "duct_equivalent_length_m": {"type": "number", "description": "System duct equivalent length, m (default 100)."},
                },
            },
            "plant": {
                "type": "object",
                "description": "Water-side plant parameters.",
                "properties": {
                    "chiller_cop": {"type": "number", "description": "Chiller COP at design conditions (default 5.5)."},
                    "boiler_efficiency": {"type": "number", "description": "Boiler thermal efficiency (default 0.92)."},
                    "has_chiller": {"type": "boolean", "description": "AHU served by chiller (default true)."},
                    "has_boiler": {"type": "boolean", "description": "AHU served by boiler (default true)."},
                },
            },
        },
    },
)


@register(_airside_system_spec)
def handle_airside_system_model(args: dict) -> str:
    try:
        from kerf_hvac.airside import (
            AirState, AHUConfig, VAVZone, PlantCoupling, simulate_ahu_system,
        )

        # -- Parse outdoor air --
        oa_raw = args["outdoor_air"]
        T_oa = float(oa_raw["T_db_C"])
        if "W_kg_kgda" in oa_raw:
            oa_state = AirState(T_db_C=T_oa, W=float(oa_raw["W_kg_kgda"]))
        else:
            rh_oa = float(oa_raw.get("rh_fraction", 0.55))
            oa_state = AirState.from_T_rh(T_oa, rh_oa)

        # -- Parse return air --
        ra_raw = args["return_air"]
        T_ra = float(ra_raw["T_db_C"])
        if "W_kg_kgda" in ra_raw:
            ra_state = AirState(T_db_C=T_ra, W=float(ra_raw["W_kg_kgda"]))
        else:
            rh_ra = float(ra_raw.get("rh_fraction", 0.50))
            ra_state = AirState.from_T_rh(T_ra, rh_ra)

        # -- Parse zones --
        zones_raw = args.get("zones", [])
        if not isinstance(zones_raw, list) or len(zones_raw) == 0:
            return err_payload("zones must be a non-empty list", "BAD_ARGS")

        zones: list[VAVZone] = []
        for zr in zones_raw:
            name = str(zr["name"])
            q_design = float(zr["design_flow_m3s"])
            load_W = float(zr["zone_load_W"])
            T_set = float(zr.get("zone_T_setpoint_C", 22.0))
            T_cur = float(zr.get("zone_T_current_C", T_set + 2.0))
            min_frac = float(zr.get("min_flow_fraction", 0.25))
            zones.append(VAVZone(
                name=name,
                design_flow_m3s=q_design,
                min_flow_fraction=min_frac,
                zone_load_W=load_W,
                zone_T_setpoint_C=T_set,
                zone_T_current_C=T_cur,
            ))

        # -- Parse AHU config --
        ahu_raw = args.get("ahu", {})
        total_design_flow = sum(z.design_flow_m3s for z in zones)
        ahu = AHUConfig(
            name=str(ahu_raw.get("name", "AHU-1")),
            supply_airflow_m3s=float(ahu_raw.get("supply_airflow_m3s", total_design_flow)),
            min_oa_fraction=float(ahu_raw.get("min_oa_fraction", 0.15)),
            economizer_setpoint_C=float(ahu_raw.get("economizer_setpoint_C", 18.0)),
            enable_economizer=bool(ahu_raw.get("enable_economizer", True)),
            enable_enthalpy_economizer=bool(ahu_raw.get("enable_enthalpy_economizer", True)),
            chw_supply_T_C=float(ahu_raw.get("chw_supply_T_C", 7.0)),
            chw_return_T_C=float(ahu_raw.get("chw_return_T_C", 12.0)),
            cooling_coil_bypass_factor=float(ahu_raw.get("cooling_coil_bypass_factor", 0.10)),
            hw_supply_T_C=float(ahu_raw.get("hw_supply_T_C", 60.0)),
            hw_return_T_C=float(ahu_raw.get("hw_return_T_C", 45.0)),
            heating_coil_effectiveness=float(ahu_raw.get("heating_coil_effectiveness", 0.80)),
            supply_fan_efficiency=float(ahu_raw.get("supply_fan_efficiency", 0.70)),
            supply_fan_motor_efficiency=float(ahu_raw.get("supply_fan_motor_efficiency", 0.92)),
            return_fan_efficiency=float(ahu_raw.get("return_fan_efficiency", 0.65)),
            return_fan_motor_efficiency=float(ahu_raw.get("return_fan_motor_efficiency", 0.90)),
            duct_equivalent_length_m=float(ahu_raw.get("duct_equivalent_length_m", 100.0)),
            duct_velocity_m_s=float(ahu_raw.get("duct_velocity_m_s", 5.0)),
            num_elbows=int(ahu_raw.get("num_elbows", 4)),
            duct_static_safety=float(ahu_raw.get("duct_static_safety", 1.15)),
        )

        # -- Parse plant coupling --
        plant_raw = args.get("plant", {})
        plant = PlantCoupling(
            chiller_cop=float(plant_raw.get("chiller_cop", 5.5)),
            boiler_efficiency=float(plant_raw.get("boiler_efficiency", 0.92)),
            has_chiller=bool(plant_raw.get("has_chiller", True)),
            has_boiler=bool(plant_raw.get("has_boiler", True)),
        )

        # -- Simulate --
        result = simulate_ahu_system(
            ahu=ahu,
            outdoor_air_state=oa_state,
            return_air_state=ra_state,
            zones=zones,
            plant=plant,
        )

        # -- Serialise --
        out = {
            "ahu_name": ahu.name,

            # Psychrometric state points
            "state_points": {
                "outdoor_air": result.outdoor_air.to_dict(),
                "return_air": result.return_air.to_dict(),
                "mixed_air": result.mixed_air.to_dict(),
                "post_cooling_coil": result.post_cooling_coil.to_dict(),
                "supply_air": result.supply_air.to_dict(),
            },

            # Economizer
            "economizer": {
                "oa_fraction": round(result.oa_fraction, 3),
                "free_cooling_active": result.free_cooling,
                "free_cooling_load_W": round(result.free_cooling_load_W, 1),
                "oa_description": (
                    "Full economizer free cooling (100% OA)"
                    if result.free_cooling else
                    f"Minimum OA ({round(result.oa_fraction*100,1)}%)"
                ),
            },

            # Cooling coil
            "cooling_coil": {
                "Q_total_W": round(result.cooling_coil_Q_total_W, 1),
                "Q_total_kW": round(result.cooling_coil_Q_total_W / 1000, 3),
                "Q_sensible_W": round(result.cooling_coil_Q_sensible_W, 1),
                "Q_latent_W": round(result.cooling_coil_Q_latent_W, 1),
                "SHR": round(
                    result.cooling_coil_Q_sensible_W / result.cooling_coil_Q_total_W, 3
                ) if result.cooling_coil_Q_total_W > 0 else 1.0,
                "ADP_C": round(result.cooling_coil_ADP_C, 2),
                "bypass_factor": round(result.cooling_coil_bypass_factor, 3),
                "effectiveness": round(result.cooling_coil_effectiveness, 3),
                "condensate_kg_s": round(result.condensate_kg_s, 6),
                "condensate_L_hr": round(result.condensate_kg_s * 3600, 2),
            },

            # Heating coil
            "heating_coil": {
                "Q_W": round(result.heating_coil_Q_W, 1),
                "Q_kW": round(result.heating_coil_Q_W / 1000, 3),
                "active": result.heating_coil_Q_W > 0,
            },

            # Fans
            "supply_fan": {
                "flow_m3s": round(result.supply_fan_flow_m3s, 4),
                "static_pressure_pa": round(result.supply_fan_static_pa, 1),
                "shaft_power_W": round(result.supply_fan_power_W, 1),
                "motor_power_W": round(result.supply_fan_motor_power_W, 1),
                "temp_rise_C": round(result.supply_fan_temp_rise_C, 3),
            },
            "return_fan": {
                "flow_m3s": round(result.return_fan_flow_m3s, 4),
                "static_pressure_pa": round(result.return_fan_static_pa, 1),
                "motor_power_W": round(result.return_fan_motor_power_W, 1),
            },
            "total_fan_power_W": round(result.total_fan_power_W, 1),
            "total_fan_power_kW": round(result.total_fan_power_W / 1000, 3),

            # VAV zones
            "vav_zones": [
                {
                    "zone": zr.zone_name,
                    "supply_flow_m3s": round(zr.supply_flow_m3s, 4),
                    "supply_T_C": round(zr.supply_T_C, 2),
                    "zone_load_met_W": round(zr.zone_load_met_W, 1),
                    "fraction_of_design": round(zr.fraction_of_design, 3),
                    "damper_position_pct": round(zr.damper_position * 100, 1),
                    "unmet_load_W": round(zr.unmet_load_W, 1),
                }
                for zr in result.zone_results
            ],
            "total_zone_flow_m3s": round(result.total_zone_flow_m3s, 4),
            "total_zone_load_met_W": round(result.total_zone_load_met_W, 1),

            # Plant coupling
            "plant": {
                "chiller_load_W": round(result.chiller_load_W, 1),
                "chiller_load_kW": round(result.chiller_load_W / 1000, 3),
                "chiller_power_W": round(result.chiller_power_W, 1),
                "chiller_power_kW": round(result.chiller_power_W / 1000, 3),
                "boiler_load_W": round(result.boiler_load_W, 1),
                "boiler_fuel_W": round(result.boiler_fuel_W, 1),
                "total_system_power_kW": round(result.total_system_power_W / 1000, 3),
            },

            # Duct system
            "duct_system": {
                "static_pressure_pa": round(result.duct_static_pressure_pa, 1),
            },

            # Energy balance
            "energy_balance_W": round(result.energy_balance_W, 1),
        }

        return ok_payload(out)

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
    ("hvac.equal_friction_sizing", _equal_friction_sizing_spec, handle_equal_friction_sizing),
    ("hvac.size_duct_run", _size_duct_run_spec, handle_size_duct_run),
    ("hvac.airside_system_model", _airside_system_spec, handle_airside_system_model),
]
