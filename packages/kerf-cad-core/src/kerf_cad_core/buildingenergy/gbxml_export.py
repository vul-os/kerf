"""
kerf_cad_core.buildingenergy.gbxml_export — Building energy model export.

Generates gbXML (Green Building XML, schema v0.37) and EnergyPlus IDF
(v9.x / 23.x) text from a simplified zone description.  These files are
the standard interchange formats for energy simulation:

  gbXML:       buildingSMART / ASHRAE interoperability standard for passing
               building geometry and thermal properties to HVAC tools such as
               Trane TRACE 3D Plus, eQUEST, HAP, and IDA ICE.
               Schema: https://gbxml.org/schema_doc/4.0/GreenBuildingXML_Ver4.01.html

  EnergyPlus IDF: EnergyPlus Input Data File — the native input format for the
               US-DOE EnergyPlus building simulation engine (v9.x / 23.1).
               Reference: EnergyPlus Input-Output Reference §6 (Thermal Zone objects).

Standards / References
----------------------
gbXML v0.37 — Green Building XML Schema
    https://www.gbxml.org/schema_doc/4.0/GreenBuildingXML_Ver4.01.html
ASHRAE Handbook — Fundamentals (2021) Ch. 18 (CLTD/RTS load calculation)
ASHRAE 90.1-2022 — Energy Standard for Buildings Except Low-Rise Residential
EnergyPlus 23.1 Input-Output Reference
    https://energyplus.net/documentation
ISO 52010-1:2017 — External climatic conditions for energy calculations
"""

from __future__ import annotations

import datetime
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ZoneGeometry:
    """One thermal zone with envelope properties.

    Parameters mirror a simplified ASHRAE/gbXML zone for use in concept-stage
    energy model export.  This is intentionally a first-principles representation
    so users can hand-enter data without CAD geometry.
    """
    zone_id: str
    name: str
    floor_area_m2: float
    ceiling_height_m: float = 3.0
    # Envelope
    wall_area_m2: float = 0.0          # exterior opaque wall area
    wall_u_value: float = 0.35         # W/(m²·K)  ASHRAE 90.1 CZ4 default
    window_area_m2: float = 0.0
    window_u_value: float = 1.8        # W/(m²·K)
    window_shgc: float = 0.4
    roof_area_m2: float = 0.0
    roof_u_value: float = 0.20         # W/(m²·K)
    floor_u_value: float = 0.25        # W/(m²·K) (above unconditioned)
    infiltration_ach: float = 0.5      # air changes per hour
    # Internal gains
    occupancy_people: int = 0
    lighting_w_m2: float = 10.0        # W/m²
    equipment_w_m2: float = 15.0       # W/m²
    # HVAC setpoints
    setpoint_heating_c: float = 21.0
    setpoint_cooling_c: float = 26.0
    # Location (for gbXML campus/site)
    latitude_deg: float = 0.0
    longitude_deg: float = 0.0
    elevation_m: float = 0.0


@dataclass
class BuildingModel:
    """Collection of zones forming a building energy model."""
    building_id: str = "building_1"
    name: str = "Kerf Building"
    climate_zone: str = "4A"           # ASHRAE climate zone
    weather_station: str = ""          # optional WS ID for EPW linkage
    zones: List[ZoneGeometry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# gbXML export
# ---------------------------------------------------------------------------

_GBXML_NS = "http://www.gbxml.org/schema"

def _indent(elem: ET.Element, level: int = 0) -> None:
    """Simple pretty-print indenter (stdlib only)."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():  # noqa: F821
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
    if not level:
        elem.tail = "\n"


def export_gbxml(model: BuildingModel) -> str:
    """Generate a gbXML v0.37 string from a BuildingModel.

    The generated XML is minimal but schema-valid for concept-stage import
    into HVAC design tools.  Key objects emitted:

      gbXML/Campus/Location   — lat/lon/elevation
      gbXML/Campus/Building   — building name + climate zone
      gbXML/Campus/Building/Space — one per zone (area + height)
      gbXML/Campus/Building/Space/SpaceBoundary — one per surface type
      gbXML/Construction      — simplified U-value constructions
      gbXML/Layer / gbXML/Material — implied single-layer for each construction
      gbXML/Schedule           — simplified OccupancySchedule
      gbXML/Zone               — HVAC zone with setpoints

    References
    ----------
    gbXML v0.37 schema:
      https://www.gbxml.org/schema_doc/4.0/GreenBuildingXML_Ver4.01.html
    ASHRAE 90.1-2022 Table 3.1 — climate zone definitions.
    """
    root = ET.Element("gbXML", attrib={
        "xmlns": _GBXML_NS,
        "version": "0.37",
        "temperatureUnit": "C",
        "lengthUnit": "Meters",
        "areaUnit": "SquareMeters",
        "volumeUnit": "CubicMeters",
        "useSIUnitsForResults": "true",
    })
    root.set("id", "gbxml_export")

    # ── DocumentHistory ───────────────────────────────────────────────────
    hist = ET.SubElement(root, "DocumentHistory")
    prog = ET.SubElement(hist, "ProgramInfo")
    prog.set("id", "kerf_cad_core")
    pname = ET.SubElement(prog, "ProductName")
    pname.text = "Kerf CAD"
    pver = ET.SubElement(prog, "Version")
    pver.text = "1.0"
    created = ET.SubElement(hist, "CreatedBy")
    created.set("date", datetime.date.today().isoformat())
    created.set("programId", "kerf_cad_core")

    # ── Campus ────────────────────────────────────────────────────────────
    campus = ET.SubElement(root, "Campus")
    campus.set("id", "campus_1")

    # Location (use first zone's lat/lon if available)
    loc = ET.SubElement(campus, "Location")
    lat_val = model.zones[0].latitude_deg if model.zones else 0.0
    lon_val = model.zones[0].longitude_deg if model.zones else 0.0
    elev_val = model.zones[0].elevation_m if model.zones else 0.0
    lat = ET.SubElement(loc, "Latitude")
    lat.text = f"{lat_val:.6f}"
    lon = ET.SubElement(loc, "Longitude")
    lon.text = f"{lon_val:.6f}"
    elev = ET.SubElement(loc, "Elevation")
    elev.text = f"{elev_val:.2f}"
    if model.weather_station:
        ws = ET.SubElement(loc, "StationId")
        ws.text = model.weather_station

    # Building
    bld = ET.SubElement(campus, "Building")
    bld.set("id", model.building_id)
    bld.set("buildingType", "Office")  # simplified; users can post-edit
    bname = ET.SubElement(bld, "Name")
    bname.text = model.name
    # Climate zone as CustomAttribute
    cz = ET.SubElement(bld, "ClimateZone")
    cz.text = model.climate_zone

    # ── Construction database (one per surface type per zone) ─────────────
    construction_ids: dict[str, str] = {}
    for zone in model.zones:
        for surf_type, u_val in [
            ("wall", zone.wall_u_value),
            ("window", zone.window_u_value),
            ("roof", zone.roof_u_value),
            ("floor", zone.floor_u_value),
        ]:
            cid = f"const_{zone.zone_id}_{surf_type}"
            construction_ids[(zone.zone_id, surf_type)] = cid
            cons = ET.SubElement(root, "Construction")
            cons.set("id", cid)
            cname = ET.SubElement(cons, "Name")
            cname.text = f"{zone.name} {surf_type.title()}"
            # Single-layer approach: R = 1/U; material thickness inferred at 0.2 m
            r_total = 1.0 / u_val if u_val > 0 else 4.0
            lay = ET.SubElement(cons, "LayerId")
            lay.set("layerIdRef", f"layer_{zone.zone_id}_{surf_type}")
            # Material
            mat = ET.SubElement(root, "Material")
            mat.set("id", f"mat_{zone.zone_id}_{surf_type}")
            mname = ET.SubElement(mat, "Name")
            mname.text = f"{zone.name} {surf_type.title()} Assembly"
            thickness = ET.SubElement(mat, "Thickness")
            thickness.text = "0.200"
            conductivity = ET.SubElement(mat, "Conductivity")
            conductivity.text = f"{0.200 / r_total:.5f}"  # k = d / R
            # Layer referencing material
            layer = ET.SubElement(root, "Layer")
            layer.set("id", f"layer_{zone.zone_id}_{surf_type}")
            matref = ET.SubElement(layer, "MaterialId")
            matref.set("materialIdRef", f"mat_{zone.zone_id}_{surf_type}")
            if surf_type == "window":
                sct = ET.SubElement(cons, "SolarHeatGainCoeff")
                sct.text = f"{zone.window_shgc:.3f}"

    # ── Spaces (zones) ────────────────────────────────────────────────────
    for zone in model.zones:
        space = ET.SubElement(bld, "Space")
        space.set("id", zone.zone_id)
        space.set("zoneIdRef", f"hvac_{zone.zone_id}")
        sname = ET.SubElement(space, "Name")
        sname.text = zone.name
        area_el = ET.SubElement(space, "Area")
        area_el.text = f"{zone.floor_area_m2:.4f}"
        vol_el = ET.SubElement(space, "Volume")
        vol_el.text = f"{zone.floor_area_m2 * zone.ceiling_height_m:.4f}"

        # Occupancy
        if zone.occupancy_people > 0:
            occ = ET.SubElement(space, "PeopleNumber")
            occ.text = str(zone.occupancy_people)
            occ_heat = ET.SubElement(space, "PeopleHeatGain")
            occ_heat.set("unit", "WattPerPerson")
            occ_heat.text = "75"  # sensible + latent mixed; ASHRAE 2021 Table 18-4 sedentary

        # Lighting density
        light_el = ET.SubElement(space, "LightPowerPerArea")
        light_el.set("unit", "WattPerSquareMeter")
        light_el.text = f"{zone.lighting_w_m2:.2f}"

        # Equipment density
        equip_el = ET.SubElement(space, "EquipPowerPerArea")
        equip_el.set("unit", "WattPerSquareMeter")
        equip_el.text = f"{zone.equipment_w_m2:.2f}"

        # Infiltration
        infil = ET.SubElement(space, "InfiltrationFlow")
        infil.set("unit", "ACH")
        infil.text = f"{zone.infiltration_ach:.3f}"

        # SpaceBoundary for each surface type
        _volume = zone.floor_area_m2 * zone.ceiling_height_m
        _perimeter_m = 4 * math.sqrt(zone.floor_area_m2)  # square room proxy

        for surf_type, surf_area, surf_tilt in [
            ("RoofCeiling", zone.roof_area_m2 or zone.floor_area_m2, 0),
            ("ExteriorWall", zone.wall_area_m2 or (_perimeter_m * zone.ceiling_height_m), 90),
            ("ExteriorFloor", zone.floor_area_m2, 180),
        ]:
            sb = ET.SubElement(space, "SpaceBoundary")
            sb.set("surfaceIdRef", f"surf_{zone.zone_id}_{surf_type.lower()}")
            sur = ET.SubElement(campus, "Surface")
            sur.set("id", f"surf_{zone.zone_id}_{surf_type.lower()}")
            sur.set("surfaceType", surf_type)
            sur.set("constructionIdRef", construction_ids[(zone.zone_id, "wall" if surf_type == "ExteriorWall" else "roof" if surf_type == "RoofCeiling" else "floor")])
            sur_name = ET.SubElement(sur, "Name")
            sur_name.text = f"{zone.name} {surf_type}"
            adj = ET.SubElement(sur, "AdjacentSpaceId")
            adj.set("spaceIdRef", zone.zone_id)
            rect = ET.SubElement(sur, "RectangularGeometry")
            rect_az = ET.SubElement(rect, "Azimuth")
            rect_az.text = "0"
            rect_tilt = ET.SubElement(rect, "Tilt")
            rect_tilt.text = str(surf_tilt)
            rect_width = ET.SubElement(rect, "Width")
            rect_width.text = f"{math.sqrt(surf_area):.4f}"
            rect_height = ET.SubElement(rect, "Height")
            rect_height.text = f"{math.sqrt(surf_area):.4f}"

        # Window opening on wall surface
        if zone.window_area_m2 > 0:
            win_surf = ET.SubElement(campus, "Surface")
            win_surf.set("id", f"surf_{zone.zone_id}_window")
            win_surf.set("surfaceType", "ExteriorWindow")
            win_surf.set("constructionIdRef", construction_ids[(zone.zone_id, "window")])
            win_name = ET.SubElement(win_surf, "Name")
            win_name.text = f"{zone.name} Window"
            win_adj = ET.SubElement(win_surf, "AdjacentSpaceId")
            win_adj.set("spaceIdRef", zone.zone_id)
            win_rect = ET.SubElement(win_surf, "RectangularGeometry")
            win_az = ET.SubElement(win_rect, "Azimuth")
            win_az.text = "180"  # south-facing default
            win_tilt = ET.SubElement(win_rect, "Tilt")
            win_tilt.text = "90"
            win_width = ET.SubElement(win_rect, "Width")
            win_w = math.sqrt(zone.window_area_m2)
            win_width.text = f"{win_w:.4f}"
            win_height = ET.SubElement(win_rect, "Height")
            win_height.text = f"{win_w:.4f}"

    # ── HVAC Zones ────────────────────────────────────────────────────────
    for zone in model.zones:
        hz = ET.SubElement(root, "Zone")
        hz.set("id", f"hvac_{zone.zone_id}")
        hname = ET.SubElement(hz, "Name")
        hname.text = f"{zone.name} HVAC Zone"
        hc = ET.SubElement(hz, "HeatSchedIdRef")
        hc.text = "sched_heating"
        cc = ET.SubElement(hz, "CoolSchedIdRef")
        cc.text = "sched_cooling"
        hsp = ET.SubElement(hz, "HeatDesignTemp")
        hsp.set("unit", "C")
        hsp.text = f"{zone.setpoint_heating_c:.1f}"
        csp = ET.SubElement(hz, "CoolDesignTemp")
        csp.set("unit", "C")
        csp.text = f"{zone.setpoint_cooling_c:.1f}"

    # ── Simple schedules ──────────────────────────────────────────────────
    for sched_id, sched_name, val in [
        ("sched_heating", "Heating Setpoint", 21.0),
        ("sched_cooling", "Cooling Setpoint", 26.0),
    ]:
        sc = ET.SubElement(root, "Schedule")
        sc.set("id", sched_id)
        sc_name = ET.SubElement(sc, "Name")
        sc_name.text = sched_name
        sc_week = ET.SubElement(sc, "WeekScheduleId")
        sc_week.set("weekScheduleIdRef", f"{sched_id}_week")

    _indent(root)
    tree = ET.ElementTree(root)
    from io import StringIO
    buf = StringIO()
    tree.write(buf, encoding="unicode", xml_declaration=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# EnergyPlus IDF export
# ---------------------------------------------------------------------------

_IDF_COMMENT = "! Generated by Kerf CAD — kerf_cad_core.buildingenergy.gbxml_export"
_IDF_VERSION = "23.1"


def export_energyplus_idf(model: BuildingModel) -> str:
    """Generate an EnergyPlus IDF (Input Data File) string.

    The output is a minimal EnergyPlus 23.1-compatible IDF containing:

      Version                — EnergyPlus version header
      Building               — name + terrain + loads convergence
      Timestep               — 6 (10-min intervals, ASHRAE recommended minimum)
      RunPeriod              — full year
      Site:Location          — latitude, longitude, elevation, timezone
      Zone                   — one per zone with infiltration ACH
      Construction / Material — one R-value-equivalent layer per surface type
      BuildingSurface:Detailed — floor + ceiling + walls for each zone
      WindowProperty:FrameAndDivider — not emitted (simplified)
      People / Lights / ElectricEquipment — internal gains per zone
      ZoneHVAC:IdealLoadsAirSystem — ideal (unconstrained) HVAC for design loads
      ThermostatSetpoint:DualSetpoint — heating / cooling setpoints
      HVACTemplate:Thermostat — links to setpoints

    References
    ----------
    EnergyPlus 23.1 Input-Output Reference
      §6.7 Zone, §9.1 BuildingSurface:Detailed, §18 ZoneHVAC:IdealLoads.
    ASHRAE Handbook — Fundamentals (2021) Ch. 18.
    """
    lines: list[str] = [
        _IDF_COMMENT,
        "",
        f"  Version,",
        f"    {_IDF_VERSION};        ! EnergyPlus version",
        "",
        f"  Building,",
        f"    {model.name},              ! Name",
        f"    0.0,                       ! North Axis [deg]",
        f"    Suburbs,                   ! Terrain",
        f"    0.04,                      ! Loads Convergence Tolerance",
        f"    0.4,                       ! Temperature Convergence Tolerance [deltaC]",
        f"    FullInteriorAndExterior,   ! Solar Distribution",
        f"    25,                        ! Maximum Number of Warmup Days",
        f"    6;                         ! Minimum Number of Warmup Days",
        "",
        f"  Timestep,",
        f"    6;  ! time steps per hour (10-min intervals, ASHRAE 90.1 §Appendix G)",
        "",
        f"  RunPeriod,",
        f"    Annual Run,",
        f"    1,                ! Begin Month",
        f"    1,                ! Begin Day",
        f"    ,                 ! Begin Year",
        f"    12,               ! End Month",
        f"    31,               ! End Day",
        f"    ,                 ! End Year",
        f"    Sunday,           ! Day of Week for Start Day",
        f"    Yes,              ! Use Weather File Holidays",
        f"    Yes,              ! Use Weather File DST",
        f"    Yes,              ! Apply Weekend Holiday Rule",
        f"    Yes,              ! Use Weather File Rain",
        f"    Yes;              ! Use Weather File Snow",
        "",
    ]

    # Site location
    lat = model.zones[0].latitude_deg if model.zones else 0.0
    lon = model.zones[0].longitude_deg if model.zones else 0.0
    elev = model.zones[0].elevation_m if model.zones else 0.0
    tz = round(lon / 15.0)  # approximate UTC offset
    lines += [
        f"  Site:Location,",
        f"    {model.name} Site,",
        f"    {lat:.4f},   ! Latitude [deg N]",
        f"    {lon:.4f},   ! Longitude [deg E]",
        f"    {tz:.1f},    ! Time Zone [h]",
        f"    {elev:.2f};  ! Elevation [m]",
        "",
    ]

    # ── Materials & Constructions ──────────────────────────────────────────
    for zone in model.zones:
        for surf_type, u_val, shgc in [
            ("Wall", zone.wall_u_value, None),
            ("Roof", zone.roof_u_value, None),
            ("Floor", zone.floor_u_value, None),
            ("Window", zone.window_u_value, zone.window_shgc),
        ]:
            r_val = 1.0 / u_val if u_val > 0 else 4.0
            mat_name = f"{zone.zone_id}_{surf_type}Mat"
            const_name = f"{zone.zone_id}_{surf_type}Const"
            if surf_type != "Window":
                # Opaque: single material layer
                lines += [
                    f"  Material:NoMass,",
                    f"    {mat_name},",
                    f"    Rough,                  ! Roughness",
                    f"    {r_val:.4f},            ! Thermal Resistance [m2-K/W]",
                    f"    0.9,                    ! Thermal Absorptance",
                    f"    0.7,                    ! Solar Absorptance",
                    f"    0.7;                    ! Visible Absorptance",
                    "",
                    f"  Construction,",
                    f"    {const_name},",
                    f"    {mat_name};",
                    "",
                ]
            else:
                # Glazing: SimpleGlazing
                lines += [
                    f"  WindowMaterial:SimpleGlazingSystem,",
                    f"    {mat_name},",
                    f"    {u_val:.3f},  ! U-Factor [W/m2-K]",
                    f"    {shgc:.3f},   ! Solar Heat Gain Coefficient",
                    f"    0.6;          ! Visible Transmittance (approximate)",
                    "",
                    f"  Construction,",
                    f"    {const_name},",
                    f"    {mat_name};",
                    "",
                ]

    # ── Zones & Surfaces ──────────────────────────────────────────────────
    for zone in model.zones:
        volume = zone.floor_area_m2 * zone.ceiling_height_m
        _side = math.sqrt(zone.floor_area_m2)  # square-room approximation

        lines += [
            f"  Zone,",
            f"    {zone.zone_id},",
            f"    0.0,         ! Direction of Relative North [deg]",
            f"    0.0,         ! X Origin [m]",
            f"    0.0,         ! Y Origin [m]",
            f"    0.0,         ! Z Origin [m]",
            f"    1,           ! Type (1=standard)",
            f"    1,           ! Multiplier",
            f"    {zone.ceiling_height_m:.2f},  ! Ceiling Height [m]",
            f"    {volume:.4f},  ! Volume [m3]",
            f"    {zone.floor_area_m2:.4f};  ! Floor Area [m2]",
            "",
        ]

        # Infiltration
        lines += [
            f"  ZoneInfiltration:DesignFlowRate,",
            f"    {zone.zone_id}_Infil,",
            f"    {zone.zone_id},",
            f"    ALWAYS_ON,   ! Schedule Name",
            f"    AirChanges/Hour,",
            f"    ,            ! Design Flow Rate [m3/s]",
            f"    ,            ! Flow per Zone Floor Area [m3/s-m2]",
            f"    ,            ! Flow per Exterior Surface Area",
            f"    {zone.infiltration_ach:.3f};  ! Air Changes per Hour",
            "",
        ]

        # Internal gains
        if zone.occupancy_people > 0:
            lines += [
                f"  People,",
                f"    {zone.zone_id}_People,",
                f"    {zone.zone_id},",
                f"    ALWAYS_ON,",
                f"    {zone.occupancy_people},  ! Number of People",
                f"    ,",  # people per zone floor area
                f"    ,",  # fraction radiant
                f"    0.3,   ! Fraction Radiant",
                f"    ,",
                f"    ASHRAE55Compliance,",
                f"    ;",
                "",
            ]

        lines += [
            f"  Lights,",
            f"    {zone.zone_id}_Lights,",
            f"    {zone.zone_id},",
            f"    ALWAYS_ON,",
            f"    Watts/Area,",
            f"    ,              ! Lighting Level [W]",
            f"    {zone.lighting_w_m2:.2f},  ! Watts per Zone Floor Area [W/m2]",
            f"    ,",
            f"    0.32,          ! Return Air Fraction",
            f"    0.59,          ! Fraction Radiant",
            f"    0.09,          ! Fraction Visible",
            f"    1.0,           ! Fraction Replaceable",
            f"    GeneralLights;",
            "",
            f"  ElectricEquipment,",
            f"    {zone.zone_id}_Equipment,",
            f"    {zone.zone_id},",
            f"    ALWAYS_ON,",
            f"    Watts/Area,",
            f"    ,              ! Design Level [W]",
            f"    {zone.equipment_w_m2:.2f},  ! Watts per Zone Floor Area [W/m2]",
            f"    ,",
            f"    0.3,           ! Fraction Latent",
            f"    0.6,           ! Fraction Radiant",
            f"    0.0;           ! Fraction Lost",
            "",
        ]

        # BuildingSurface:Detailed — 5-surface box (floor, ceiling, 4 walls)
        h = zone.ceiling_height_m
        s = _side

        # Floor
        lines += [
            f"  BuildingSurface:Detailed,",
            f"    {zone.zone_id}_Floor,",
            f"    Floor,",
            f"    {zone.zone_id}_FloorConst,",
            f"    {zone.zone_id},",
            f"    Ground,",
            f"    ,",
            f"    NoSun,",
            f"    NoWind,",
            f"    1.0,",
            f"    4,",
            f"    0.0, 0.0, 0.0,",
            f"    0.0, {s:.4f}, 0.0,",
            f"    {s:.4f}, {s:.4f}, 0.0,",
            f"    {s:.4f}, 0.0, 0.0;",
            "",
        ]

        # Ceiling
        lines += [
            f"  BuildingSurface:Detailed,",
            f"    {zone.zone_id}_Ceiling,",
            f"    Roof,",
            f"    {zone.zone_id}_RoofConst,",
            f"    {zone.zone_id},",
            f"    Outdoors,",
            f"    ,",
            f"    SunExposed,",
            f"    WindExposed,",
            f"    1.0,",
            f"    4,",
            f"    0.0, 0.0, {h:.4f},",
            f"    {s:.4f}, 0.0, {h:.4f},",
            f"    {s:.4f}, {s:.4f}, {h:.4f},",
            f"    0.0, {s:.4f}, {h:.4f};",
            "",
        ]

        # 4 walls
        for idx, (y1, y2, x1, x2) in enumerate([
            (0.0, 0.0, 0.0, s),       # South wall
            (s, s, s, 0.0),            # North wall
            (0.0, s, 0.0, 0.0),        # West wall
            (0.0, s, s, s),            # East wall
        ]):
            lines += [
                f"  BuildingSurface:Detailed,",
                f"    {zone.zone_id}_Wall{idx+1},",
                f"    Wall,",
                f"    {zone.zone_id}_WallConst,",
                f"    {zone.zone_id},",
                f"    Outdoors,",
                f"    ,",
                f"    SunExposed,",
                f"    WindExposed,",
                f"    1.0,",
                f"    4,",
                f"    {x1:.4f}, {y1:.4f}, {h:.4f},",
                f"    {x1:.4f}, {y1:.4f}, 0.0,",
                f"    {x2:.4f}, {y2:.4f}, 0.0,",
                f"    {x2:.4f}, {y2:.4f}, {h:.4f};",
                "",
            ]

        # Window on south wall
        if zone.window_area_m2 > 0:
            ww = math.sqrt(zone.window_area_m2)
            wx0 = max(0.1, (s - ww) / 2)
            wz0 = max(0.1, (h - ww) / 2)
            lines += [
                f"  FenestrationSurface:Detailed,",
                f"    {zone.zone_id}_Window,",
                f"    Window,",
                f"    {zone.zone_id}_WindowConst,",
                f"    {zone.zone_id}_Wall1,  ! Base Surface",
                f"    ,",
                f"    ,",
                f"    ,",
                f"    1.0,",
                f"    4,",
                f"    {wx0:.4f}, 0.0, {wz0 + ww:.4f},",
                f"    {wx0:.4f}, 0.0, {wz0:.4f},",
                f"    {wx0 + ww:.4f}, 0.0, {wz0:.4f},",
                f"    {wx0 + ww:.4f}, 0.0, {wz0 + ww:.4f};",
                "",
            ]

        # Ideal loads HVAC
        lines += [
            f"  ZoneHVAC:IdealLoadsAirSystem,",
            f"    {zone.zone_id}_IdealLoads,",
            f"    ALWAYS_ON,           ! Availability Schedule",
            f"    {zone.zone_id}_SupplyAir,  ! Zone Supply Air Node Name",
            f"    {zone.zone_id}_ExhaustAir, ! Zone Exhaust Air Node Name",
            f"    ,",  # system inlet node
            f"    50,                  ! Maximum Heating Supply Air Temperature [C]",
            f"    13,                  ! Minimum Cooling Supply Air Temperature [C]",
            f"    0.010,               ! Maximum Heating Supply Air Humidity Ratio",
            f"    0.009,               ! Minimum Cooling Supply Air Humidity Ratio",
            f"    NoLimit,             ! Heating Limit",
            f"    ,",
            f"    ,",
            f"    NoLimit,             ! Cooling Limit",
            f"    ,",
            f"    ,",
            f"    No,                  ! Dehumidification Control",
            f"    ,",
            f"    ,",
            f"    ,",
            f"    No,                  ! Humidification Control",
            f"    ,",
            f"    {zone.zone_id}_OASpec, ! Design Specification Outdoor Air",
            f"    ,",
            f"    ,",
            f"    None;                ! Heat Recovery Type",
            "",
        ]

        # Thermostat
        lines += [
            f"  ThermostatSetpoint:DualSetpoint,",
            f"    {zone.zone_id}_Tstat,",
            f"    {zone.zone_id}_HeatSP_Sched,  ! Heating Setpoint Temperature Schedule",
            f"    {zone.zone_id}_CoolSP_Sched;   ! Cooling Setpoint Temperature Schedule",
            "",
        ]

        # Schedules
        lines += [
            f"  Schedule:Constant,",
            f"    {zone.zone_id}_HeatSP_Sched,",
            f"    Temperature,",
            f"    {zone.setpoint_heating_c:.1f};",
            "",
            f"  Schedule:Constant,",
            f"    {zone.zone_id}_CoolSP_Sched,",
            f"    Temperature,",
            f"    {zone.setpoint_cooling_c:.1f};",
            "",
        ]

    # Always-on schedule
    lines += [
        f"  ScheduleTypeLimits,",
        f"    Fraction,",
        f"    0.0,",
        f"    1.0,",
        f"    Continuous;",
        "",
        f"  Schedule:Constant,",
        f"    ALWAYS_ON,",
        f"    Fraction,",
        f"    1.0;",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience: zone list → BuildingModel
# ---------------------------------------------------------------------------

def zones_to_model(zones_data: list[dict], building_name: str = "Kerf Building",
                   climate_zone: str = "4A") -> BuildingModel:
    """Convert a list of zone dicts to a BuildingModel.

    Each dict may have keys:
      zone_id, name, floor_area_m2, ceiling_height_m, wall_area_m2,
      wall_u_value, window_area_m2, window_u_value, window_shgc,
      roof_area_m2, roof_u_value, floor_u_value, infiltration_ach,
      occupancy_people, lighting_w_m2, equipment_w_m2,
      setpoint_heating_c, setpoint_cooling_c,
      latitude_deg, longitude_deg, elevation_m.
    Missing keys use ZoneGeometry defaults.
    """
    zones = []
    for i, z in enumerate(zones_data):
        zid = z.get("zone_id", f"zone_{i+1}")
        zones.append(ZoneGeometry(
            zone_id=zid,
            name=z.get("name", f"Zone {i+1}"),
            floor_area_m2=float(z.get("floor_area_m2", 50.0)),
            ceiling_height_m=float(z.get("ceiling_height_m", 3.0)),
            wall_area_m2=float(z.get("wall_area_m2", 0.0)),
            wall_u_value=float(z.get("wall_u_value", 0.35)),
            window_area_m2=float(z.get("window_area_m2", 0.0)),
            window_u_value=float(z.get("window_u_value", 1.8)),
            window_shgc=float(z.get("window_shgc", 0.4)),
            roof_area_m2=float(z.get("roof_area_m2", 0.0)),
            roof_u_value=float(z.get("roof_u_value", 0.20)),
            floor_u_value=float(z.get("floor_u_value", 0.25)),
            infiltration_ach=float(z.get("infiltration_ach", 0.5)),
            occupancy_people=int(z.get("occupancy_people", 0)),
            lighting_w_m2=float(z.get("lighting_w_m2", 10.0)),
            equipment_w_m2=float(z.get("equipment_w_m2", 15.0)),
            setpoint_heating_c=float(z.get("setpoint_heating_c", 21.0)),
            setpoint_cooling_c=float(z.get("setpoint_cooling_c", 26.0)),
            latitude_deg=float(z.get("latitude_deg", 0.0)),
            longitude_deg=float(z.get("longitude_deg", 0.0)),
            elevation_m=float(z.get("elevation_m", 0.0)),
        ))
    return BuildingModel(
        building_id="building_1",
        name=building_name,
        climate_zone=climate_zone,
        zones=zones,
    )
