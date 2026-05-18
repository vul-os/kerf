"""
LLM tool definitions for kerf-energy.

Tools exposed to the Kerf agent:
  energy_heat_load   — compute peak zone cooling/heating load
  energy_daylight    — estimate mean daylight factor (split-flux)
  energy_rt60        — calculate Sabine RT60 reverberation time
  energy_solar       — solar altitude/azimuth + ASHRAE clear-sky irradiance
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_energy._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_energy.acoustic import rt60_sabine
from kerf_energy.daylight import daylight_factor_split_flux, check_bs8206_compliance
from kerf_energy.heat_load import (
    ZoneHeatLoad,
    WallElement,
    GlazingElement,
    OccupancyLoad,
    LightingLoad,
    EquipmentLoad,
)
from kerf_energy.solar import (
    solar_declination_deg,
    hour_angle_deg,
    solar_position,
    clear_sky_irradiance,
    day_of_year,
)


# ---------------------------------------------------------------------------
# energy_rt60
# ---------------------------------------------------------------------------

energy_rt60_spec = ToolSpec(
    name="energy_rt60",
    description=(
        "Calculate the Sabine reverberation time RT60 for a room. "
        "RT60 = 0.161 · V / A  (seconds), where V is room volume in m³ "
        "and A is the total acoustic absorption in metric Sabines (m²)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "volume_m3": {
                "type": "number",
                "description": "Room volume in cubic metres.",
            },
            "total_absorption_sabines": {
                "type": "number",
                "description": (
                    "Total room absorption in metric Sabines (m²). "
                    "Computed as Σ(area_i × absorption_coeff_i) for all surfaces."
                ),
            },
        },
        "required": ["volume_m3", "total_absorption_sabines"],
    },
)


@register(energy_rt60_spec, write=False)
async def run_energy_rt60(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    volume_m3 = a.get("volume_m3")
    absorption = a.get("total_absorption_sabines")

    if volume_m3 is None or absorption is None:
        return err_payload("volume_m3 and total_absorption_sabines are required", "BAD_ARGS")

    try:
        rt60 = rt60_sabine(float(volume_m3), float(absorption))
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    return ok_payload({
        "rt60_seconds": round(rt60, 4),
        "volume_m3": volume_m3,
        "total_absorption_sabines": absorption,
        "method": "Sabine",
    })


# ---------------------------------------------------------------------------
# energy_daylight
# ---------------------------------------------------------------------------

energy_daylight_spec = ToolSpec(
    name="energy_daylight",
    description=(
        "Estimate the mean Daylight Factor (%) for a room using the BRS "
        "split-flux method (BS 8206-2 / IES LM-83)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "window_area_m2": {
                "type": "number",
                "description": "Total glazed aperture area (m²).",
            },
            "room_floor_area_m2": {
                "type": "number",
                "description": "Room floor area (m²).",
            },
            "tau": {
                "type": "number",
                "description": "Glazing visible-light transmittance (0–1, default 0.6).",
            },
            "sky_component_fraction": {
                "type": "number",
                "description": "Fraction of sky visible from the window (0–1, default 0.4).",
            },
            "average_reflectance": {
                "type": "number",
                "description": "Mean surface reflectance of walls/ceiling/floor (0–1, default 0.5).",
            },
            "space_type": {
                "type": "string",
                "description": (
                    "Optional space type for BS 8206-2 compliance check. "
                    "One of: kitchen, living_room, bedroom, office, classroom, corridor."
                ),
            },
        },
        "required": ["window_area_m2", "room_floor_area_m2"],
    },
)


@register(energy_daylight_spec, write=False)
async def run_energy_daylight(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    window_area = a.get("window_area_m2")
    floor_area = a.get("room_floor_area_m2")

    if window_area is None or floor_area is None:
        return err_payload("window_area_m2 and room_floor_area_m2 are required", "BAD_ARGS")

    kwargs = {}
    for k in ("tau", "sky_component_fraction", "average_reflectance"):
        if k in a:
            kwargs[k] = float(a[k])

    try:
        df = daylight_factor_split_flux(float(window_area), float(floor_area), **kwargs)
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    result: dict = {
        "daylight_factor_percent": round(df, 4),
        "window_area_m2": window_area,
        "room_floor_area_m2": floor_area,
        "method": "BS8206-2 split-flux",
    }

    space_type = a.get("space_type")
    if space_type:
        try:
            compliance = check_bs8206_compliance(space_type, df)
            result["bs8206_compliance"] = compliance
        except ValueError as e:
            result["bs8206_compliance_warning"] = str(e)

    return ok_payload(result)


# ---------------------------------------------------------------------------
# energy_solar
# ---------------------------------------------------------------------------

energy_solar_spec = ToolSpec(
    name="energy_solar",
    description=(
        "Compute solar altitude, azimuth, and ASHRAE clear-sky irradiance "
        "components (DNI, DHI, GHI) for a given site and time."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "latitude_deg": {
                "type": "number",
                "description": "Site latitude in decimal degrees (north positive).",
            },
            "longitude_deg": {
                "type": "number",
                "description": "Site longitude in decimal degrees (east positive).",
            },
            "day_of_year": {
                "type": "integer",
                "description": "Day of year (1–365).",
            },
            "solar_time_hours": {
                "type": "number",
                "description": "Apparent solar time in decimal hours (0–24).",
            },
        },
        "required": ["latitude_deg", "longitude_deg", "day_of_year", "solar_time_hours"],
    },
)


@register(energy_solar_spec, write=False)
async def run_energy_solar(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    for key in ("latitude_deg", "longitude_deg", "day_of_year", "solar_time_hours"):
        if key not in a:
            return err_payload(f"{key} is required", "BAD_ARGS")

    lat = float(a["latitude_deg"])
    lon = float(a["longitude_deg"])
    doy = int(a["day_of_year"])
    solar_time = float(a["solar_time_hours"])

    irr = clear_sky_irradiance(lat, lon, doy, solar_time)

    dec = solar_declination_deg(doy)
    ha = hour_angle_deg(solar_time)
    alt_deg, az_deg = solar_position(lat, dec, ha)

    return ok_payload({
        "solar_altitude_deg": round(alt_deg, 4),
        "solar_azimuth_deg": round(az_deg, 4),
        "solar_declination_deg": round(dec, 4),
        "hour_angle_deg": round(ha, 4),
        "direct_normal_irradiance_w_m2": round(irr.direct_normal_w_m2, 2),
        "diffuse_horizontal_irradiance_w_m2": round(irr.diffuse_horizontal_w_m2, 2),
        "global_horizontal_irradiance_w_m2": round(irr.global_horizontal_w_m2, 2),
        "day_of_year": doy,
        "method": "ASHRAE clear-sky",
    })


# ---------------------------------------------------------------------------
# energy_heat_load
# ---------------------------------------------------------------------------

energy_heat_load_spec = ToolSpec(
    name="energy_heat_load",
    description=(
        "Estimate peak zone cooling load (sensible + latent) using the "
        "ASHRAE CLTD/CLF method.  Returns peak sensible W, latent W, and "
        "the hour of peak load."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "walls": {
                "type": "array",
                "description": "List of exterior wall elements.",
                "items": {
                    "type": "object",
                    "properties": {
                        "area_m2": {"type": "number"},
                        "u_value_w_m2_k": {"type": "number"},
                        "facing": {"type": "string"},
                    },
                    "required": ["area_m2", "u_value_w_m2_k"],
                },
            },
            "glazing": {
                "type": "array",
                "description": "List of glazing elements.",
                "items": {
                    "type": "object",
                    "properties": {
                        "area_m2": {"type": "number"},
                        "u_value_w_m2_k": {"type": "number"},
                        "shgc": {"type": "number"},
                        "facing": {"type": "string"},
                    },
                    "required": ["area_m2", "u_value_w_m2_k", "shgc"],
                },
            },
            "num_people": {"type": "integer", "description": "Number of occupants."},
            "lighting_w": {"type": "number", "description": "Installed lighting power (W)."},
            "equipment_w": {"type": "number", "description": "Plug load sensible power (W)."},
        },
        "required": [],
    },
)


@register(energy_heat_load_spec, write=False)
async def run_energy_heat_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    zone = ZoneHeatLoad()

    for w in a.get("walls", []):
        zone.walls.append(WallElement(
            area_m2=float(w["area_m2"]),
            u_value_w_m2_k=float(w["u_value_w_m2_k"]),
            facing=w.get("facing", "south"),
        ))

    for g in a.get("glazing", []):
        zone.glazing.append(GlazingElement(
            area_m2=float(g["area_m2"]),
            u_value_w_m2_k=float(g["u_value_w_m2_k"]),
            shgc=float(g["shgc"]),
            facing=g.get("facing", "south"),
        ))

    num_people = a.get("num_people", 0)
    if num_people:
        zone.occupancy.append(OccupancyLoad(num_people=int(num_people)))

    lighting_w = a.get("lighting_w", 0)
    if lighting_w:
        zone.lighting.append(LightingLoad(installed_power_w=float(lighting_w)))

    equipment_w = a.get("equipment_w", 0)
    if equipment_w:
        zone.equipment.append(EquipmentLoad(sensible_w=float(equipment_w)))

    peak_h = zone.peak_hour()
    peak_sensible = zone.peak_sensible_w()
    latent = zone.latent_w()

    return ok_payload({
        "peak_sensible_w": round(peak_sensible, 1),
        "latent_w": round(latent, 1),
        "total_cooling_w": round(peak_sensible + latent, 1),
        "peak_hour": peak_h,
        "method": "ASHRAE CLTD/CLF",
    })
