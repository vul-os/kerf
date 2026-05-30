"""
LLM tool definitions for kerf-energy.

Tools exposed to the Kerf agent:
  energy_heat_load        — compute peak zone cooling/heating load
  energy_daylight         — estimate mean daylight factor (split-flux)
  energy_rt60             — calculate Sabine RT60 reverberation time
  energy_solar            — solar altitude/azimuth + ASHRAE clear-sky irradiance
  energy_poa_irradiance   — plane-of-array (POA) irradiance for tilted PV modules
  energy_sun_position     — solar zenith/azimuth from site + UTC datetime
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
from kerf_energy.pv_irradiance import (
    poa_irradiance,
    compute_sun_position,
    optimal_tilt_for_annual_pv,
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


# ---------------------------------------------------------------------------
# energy_poa_irradiance
# ---------------------------------------------------------------------------

energy_poa_irradiance_spec = ToolSpec(
    name="energy_poa_irradiance",
    description=(
        "Compute plane-of-array (POA) irradiance on a tilted PV surface. "
        "Returns poa_total, poa_beam, poa_diffuse_sky, poa_diffuse_ground (W/m²). "
        "Three transposition models available: "
        "'liu_jordan' (isotropic, conservative), "
        "'hay_davies' (anisotropic, better for clear sky), "
        "'perez' (Perez 1990, industry standard, most accurate — default). "
        "DISCLAIMER: published methods (Liu-Jordan 1960, Hay-Davies 1980, "
        "Perez 1990) — NOT NREL-certified reference code."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "direct_normal_irradiance": {
                "type": "number",
                "description": "Direct normal irradiance (DNI) in W/m².",
            },
            "diffuse_horizontal_irradiance": {
                "type": "number",
                "description": "Diffuse horizontal irradiance (DHI) in W/m².",
            },
            "ghi": {
                "type": "number",
                "description": "Global horizontal irradiance (GHI) in W/m².",
            },
            "sun_zenith_deg": {
                "type": "number",
                "description": "Solar zenith angle in degrees (0 = overhead, 90 = horizon).",
            },
            "sun_azimuth_deg": {
                "type": "number",
                "description": "Solar azimuth clockwise from north (degrees, 0–360).",
            },
            "tilt_deg": {
                "type": "number",
                "description": "Surface tilt from horizontal (degrees, 0 = flat, 90 = vertical).",
            },
            "surface_azimuth_deg": {
                "type": "number",
                "description": (
                    "Surface azimuth clockwise from north (degrees). "
                    "180 = south-facing (optimal in Northern Hemisphere)."
                ),
            },
            "ground_albedo": {
                "type": "number",
                "description": "Ground reflectance (dimensionless, default 0.2 = grass/soil).",
            },
            "model": {
                "type": "string",
                "enum": ["liu_jordan", "hay_davies", "perez"],
                "description": "Sky diffuse transposition model (default 'perez').",
            },
        },
        "required": [
            "direct_normal_irradiance",
            "diffuse_horizontal_irradiance",
            "ghi",
            "sun_zenith_deg",
            "sun_azimuth_deg",
            "tilt_deg",
            "surface_azimuth_deg",
        ],
    },
)


@register(energy_poa_irradiance_spec, write=False)
async def run_energy_poa_irradiance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = [
        "direct_normal_irradiance", "diffuse_horizontal_irradiance", "ghi",
        "sun_zenith_deg", "sun_azimuth_deg", "tilt_deg", "surface_azimuth_deg",
    ]
    for key in required:
        if key not in a:
            return err_payload(f"{key} is required", "BAD_ARGS")

    try:
        result = poa_irradiance(
            direct_normal_irradiance=float(a["direct_normal_irradiance"]),
            diffuse_horizontal_irradiance=float(a["diffuse_horizontal_irradiance"]),
            ghi=float(a["ghi"]),
            sun_zenith_deg=float(a["sun_zenith_deg"]),
            sun_azimuth_deg=float(a["sun_azimuth_deg"]),
            tilt_deg=float(a["tilt_deg"]),
            surface_azimuth_deg=float(a["surface_azimuth_deg"]),
            ground_albedo=float(a.get("ground_albedo", 0.2)),
            model=a.get("model", "perez"),
        )
    except (ValueError, KeyError) as e:
        return err_payload(str(e), "BAD_ARGS")

    tilt = float(a["tilt_deg"])
    lat_hint = 90.0 - float(a["sun_zenith_deg"])
    opt_tilt = optimal_tilt_for_annual_pv(lat_hint) if lat_hint > 0 else None

    payload = {
        "poa_total_w_m2": round(result["poa_total"], 2),
        "poa_beam_w_m2": round(result["poa_beam"], 2),
        "poa_diffuse_sky_w_m2": round(result["poa_diffuse_sky"], 2),
        "poa_diffuse_ground_w_m2": round(result["poa_diffuse_ground"], 2),
        "tilt_deg": tilt,
        "surface_azimuth_deg": float(a["surface_azimuth_deg"]),
        "model": a.get("model", "perez"),
        "disclaimer": (
            "Liu-Jordan/Hay-Davies/Perez 1990 published methods — NOT NREL-certified"
        ),
    }
    if opt_tilt is not None:
        payload["optimal_tilt_hint_deg"] = round(opt_tilt, 1)

    return ok_payload(payload)


# ---------------------------------------------------------------------------
# energy_sun_position
# ---------------------------------------------------------------------------

energy_sun_position_spec = ToolSpec(
    name="energy_sun_position",
    description=(
        "Compute solar zenith, azimuth, and altitude for a site and UTC datetime "
        "using Spencer (1971) solar geometry. Returns sun_zenith_deg, "
        "sun_azimuth_deg, sun_altitude_deg, solar_time_hours, day_of_year. "
        "Typical accuracy ±0.01–0.1° — adequate for hourly PV energy modelling. "
        "NOT the NREL SPA algorithm (Reda & Andreas 2004)."
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
            "datetime_utc": {
                "type": "string",
                "description": (
                    "UTC datetime in ISO 8601 format, e.g. '2024-06-21T12:00:00'. "
                    "Timezone suffix 'Z' or '+00:00' is accepted but not required."
                ),
            },
        },
        "required": ["latitude_deg", "longitude_deg", "datetime_utc"],
    },
)


@register(energy_sun_position_spec, write=False)
async def run_energy_sun_position(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    for key in ("latitude_deg", "longitude_deg", "datetime_utc"):
        if key not in a:
            return err_payload(f"{key} is required", "BAD_ARGS")

    try:
        from datetime import datetime, timezone

        dt_str = a["datetime_utc"].rstrip("Z").replace("+00:00", "")
        # Accept both date-only and full datetime strings
        if "T" in dt_str:
            dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(dt_str + "T12:00:00").replace(tzinfo=timezone.utc)

        result = compute_sun_position(
            latitude_deg=float(a["latitude_deg"]),
            longitude_deg=float(a["longitude_deg"]),
            datetime_utc=dt,
        )
    except (ValueError, TypeError) as e:
        return err_payload(str(e), "BAD_ARGS")

    return ok_payload({
        **result,
        "method": "Spencer (1971) — NOT NREL SPA",
    })
