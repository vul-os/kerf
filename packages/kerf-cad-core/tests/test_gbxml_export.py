"""
Tests for kerf_cad_core.buildingenergy.gbxml_export and the
be_export_energy_model LLM tool.

Oracles
-------
1. export_gbxml — output is valid UTF-8 XML; root element is <gbXML>.
2. export_gbxml — version attribute = '0.37'.
3. export_gbxml — zone names appear in output.
4. export_gbxml — SHGC value appears in window Construction element.
5. export_energyplus_idf — output contains 'Zone,' IDF object keyword.
6. export_energyplus_idf — output contains ZoneHVAC:IdealLoadsAirSystem.
7. export_energyplus_idf — setpoint values appear in Schedule:Constant.
8. export_energyplus_idf — version header present.
9. zones_to_model — default values applied for optional fields.
10. Tool handler — valid 1-zone gbxml export → ok payload with content key.
11. Tool handler — valid 1-zone idf export → ok payload, filename ends .idf.
12. Tool handler — empty zones list → {"ok": false} response.
13. Tool handler — invalid format → {"ok": false} response.
14. Multi-zone export — all zone IDs appear in gbXML output.
15. R-value consistency — Material conductivity = 0.2 / (1/U) in gbXML Material.

References
----------
gbXML v0.37 schema — https://www.gbxml.org/schema_doc/4.0/GreenBuildingXML_Ver4.01.html
ASHRAE 90.1-2022 — envelope U-value defaults.
EnergyPlus 23.1 Input-Output Reference — §6.7 Zone.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

import pytest

# Ensure all packages/*/src are on sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_CAD_ROOT = os.path.dirname(_HERE)
_PACKAGES_ROOT = os.path.dirname(_CAD_ROOT)
for _entry in os.listdir(_PACKAGES_ROOT):
    if _entry.startswith("kerf-"):
        _src = os.path.join(_PACKAGES_ROOT, _entry, "src")
        if os.path.isdir(_src) and _src not in sys.path:
            sys.path.insert(0, _src)

from kerf_cad_core.buildingenergy.gbxml_export import (
    BuildingModel,
    ZoneGeometry,
    export_gbxml,
    export_energyplus_idf,
    zones_to_model,
)

# Tool handler imports (from buildingenergy/tools.py)
from kerf_cad_core.buildingenergy.tools import run_export_energy_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeCtx:
    pass


def single_zone_model(
    zone_id="z1", name="Office", floor_area=80.0,
    window_area=12.0, window_u=1.8, window_shgc=0.4,
    wall_u=0.35, roof_u=0.20,
    setpoint_h=21.0, setpoint_c=26.0,
):
    return BuildingModel(
        building_id="bldg_1",
        name="Test Building",
        climate_zone="4A",
        zones=[ZoneGeometry(
            zone_id=zone_id,
            name=name,
            floor_area_m2=floor_area,
            ceiling_height_m=3.0,
            wall_area_m2=0.0,
            wall_u_value=wall_u,
            window_area_m2=window_area,
            window_u_value=window_u,
            window_shgc=window_shgc,
            roof_area_m2=0.0,
            roof_u_value=roof_u,
            floor_u_value=0.25,
            infiltration_ach=0.5,
            occupancy_people=4,
            lighting_w_m2=10.0,
            equipment_w_m2=15.0,
            setpoint_heating_c=setpoint_h,
            setpoint_cooling_c=setpoint_c,
            latitude_deg=51.5,
            longitude_deg=-0.1,
        )],
    )


# ---------------------------------------------------------------------------
# Oracle 1 — gbXML output is valid XML
# ---------------------------------------------------------------------------

class TestGbxmlValidXML:
    def test_output_is_parseable_xml(self):
        model = single_zone_model()
        xml_str = export_gbxml(model)
        # Must not raise
        root = ET.fromstring(xml_str)
        assert root.tag.endswith("gbXML"), f"Root tag is {root.tag}"

    def test_root_is_utf8_parseable(self):
        model = single_zone_model()
        xml_str = export_gbxml(model)
        # encoding=unicode means header says encoding="us-ascii" or utf-8
        assert isinstance(xml_str, str)
        xml_str.encode("utf-8")  # no UnicodeEncodeError


# ---------------------------------------------------------------------------
# Oracle 2 — version attribute = '0.37'
# ---------------------------------------------------------------------------

class TestGbxmlVersion:
    def test_version_attribute_is_037(self):
        model = single_zone_model()
        xml_str = export_gbxml(model)
        root = ET.fromstring(xml_str)
        assert root.get("version") == "0.37", f"version={root.get('version')}"


# ---------------------------------------------------------------------------
# Oracle 3 — zone name appears in output
# ---------------------------------------------------------------------------

class TestGbxmlZoneName:
    def test_zone_name_in_gbxml(self):
        model = single_zone_model(name="LobbyZone")
        xml_str = export_gbxml(model)
        assert "LobbyZone" in xml_str, "Zone name not found in gbXML output"

    def test_building_name_in_gbxml(self):
        model = single_zone_model()
        xml_str = export_gbxml(model)
        assert "Test Building" in xml_str


# ---------------------------------------------------------------------------
# Oracle 4 — SHGC value appears in window Construction
# ---------------------------------------------------------------------------

class TestGbxmlSHGC:
    def test_shgc_present_in_gbxml(self):
        model = single_zone_model(window_shgc=0.38)
        xml_str = export_gbxml(model)
        assert "0.380" in xml_str or "0.38" in xml_str, (
            "SHGC=0.38 not found in gbXML output"
        )


# ---------------------------------------------------------------------------
# Oracle 5 — IDF contains Zone keyword
# ---------------------------------------------------------------------------

class TestIdfZoneObject:
    def test_idf_contains_zone_keyword(self):
        model = single_zone_model()
        idf_str = export_energyplus_idf(model)
        assert "Zone," in idf_str, "EnergyPlus IDF missing 'Zone,' keyword"

    def test_idf_zone_id_present(self):
        model = single_zone_model(zone_id="office_1")
        idf_str = export_energyplus_idf(model)
        assert "office_1" in idf_str


# ---------------------------------------------------------------------------
# Oracle 6 — IDF contains IdealLoads
# ---------------------------------------------------------------------------

class TestIdfIdealLoads:
    def test_idf_has_ideal_loads(self):
        model = single_zone_model()
        idf_str = export_energyplus_idf(model)
        assert "ZoneHVAC:IdealLoadsAirSystem" in idf_str


# ---------------------------------------------------------------------------
# Oracle 7 — IDF setpoints appear in Schedule:Constant
# ---------------------------------------------------------------------------

class TestIdfSetpoints:
    def test_heating_setpoint_in_idf(self):
        model = single_zone_model(setpoint_h=19.0, setpoint_c=25.0)
        idf_str = export_energyplus_idf(model)
        assert "19.0" in idf_str, "Heating setpoint 19.0 not found in IDF"

    def test_cooling_setpoint_in_idf(self):
        model = single_zone_model(setpoint_h=21.0, setpoint_c=24.0)
        idf_str = export_energyplus_idf(model)
        assert "24.0" in idf_str, "Cooling setpoint 24.0 not found in IDF"


# ---------------------------------------------------------------------------
# Oracle 8 — IDF version header present
# ---------------------------------------------------------------------------

class TestIdfVersion:
    def test_idf_has_version_object(self):
        model = single_zone_model()
        idf_str = export_energyplus_idf(model)
        assert "Version," in idf_str
        assert "23.1" in idf_str


# ---------------------------------------------------------------------------
# Oracle 9 — zones_to_model defaults
# ---------------------------------------------------------------------------

class TestZonesToModel:
    def test_defaults_applied(self):
        model = zones_to_model([{"zone_id": "z1", "floor_area_m2": 50}])
        z = model.zones[0]
        assert z.ceiling_height_m == 3.0
        assert z.wall_u_value == 0.35
        assert z.window_u_value == 1.8
        assert z.window_shgc == 0.4
        assert z.infiltration_ach == 0.5
        assert z.setpoint_heating_c == 21.0

    def test_custom_values_applied(self):
        model = zones_to_model([{
            "zone_id": "z2",
            "floor_area_m2": 100,
            "wall_u_value": 0.20,
            "setpoint_heating_c": 19.0,
        }])
        z = model.zones[0]
        assert z.floor_area_m2 == 100.0
        assert z.wall_u_value == 0.20
        assert z.setpoint_heating_c == 19.0


# ---------------------------------------------------------------------------
# Oracle 10 — tool handler: valid 1-zone gbxml export
# ---------------------------------------------------------------------------

class TestToolHandlerGbxml:
    def test_valid_single_zone_gbxml(self):
        args_bytes = json.dumps({
            "format": "gbxml",
            "building_name": "Tool Test Building",
            "climate_zone": "3A",
            "zones": [{"zone_id": "z1", "floor_area_m2": 60, "window_area_m2": 8}],
        }).encode()
        result_str = run_async(run_export_energy_model(FakeCtx(), args_bytes))
        result = json.loads(result_str)
        assert "content" in result, f"Missing content key: {result}"
        assert result.get("format") == "gbxml"
        assert result.get("filename", "").endswith(".gbxml")
        assert "<gbXML" in result["content"]
        assert result.get("n_zones") == 1

    def test_gbxml_content_parseable(self):
        args_bytes = json.dumps({
            "format": "gbxml",
            "zones": [{"zone_id": "z1", "floor_area_m2": 60}],
        }).encode()
        result_str = run_async(run_export_energy_model(FakeCtx(), args_bytes))
        result = json.loads(result_str)
        # Must be parseable XML
        ET.fromstring(result["content"])


# ---------------------------------------------------------------------------
# Oracle 11 — tool handler: valid 1-zone IDF export
# ---------------------------------------------------------------------------

class TestToolHandlerIdf:
    def test_valid_single_zone_idf(self):
        args_bytes = json.dumps({
            "format": "idf",
            "building_name": "IDF Test",
            "zones": [{"zone_id": "z1", "floor_area_m2": 80, "occupancy_people": 4}],
        }).encode()
        result_str = run_async(run_export_energy_model(FakeCtx(), args_bytes))
        result = json.loads(result_str)
        assert "content" in result
        assert result.get("filename", "").endswith(".idf")
        assert "Zone," in result["content"]


# ---------------------------------------------------------------------------
# Oracle 12 — empty zones list → error
# ---------------------------------------------------------------------------

class TestToolHandlerEmptyZones:
    def test_empty_zones_returns_error(self):
        args_bytes = json.dumps({"zones": []}).encode()
        result_str = run_async(run_export_energy_model(FakeCtx(), args_bytes))
        result = json.loads(result_str)
        assert result.get("ok") is False or "error" in result or "reason" in result

    def test_missing_zones_returns_error(self):
        args_bytes = json.dumps({"format": "gbxml"}).encode()
        result_str = run_async(run_export_energy_model(FakeCtx(), args_bytes))
        result = json.loads(result_str)
        assert result.get("ok") is False or "reason" in result


# ---------------------------------------------------------------------------
# Oracle 13 — invalid format
# ---------------------------------------------------------------------------

class TestToolHandlerInvalidFormat:
    def test_bad_format_returns_error(self):
        args_bytes = json.dumps({
            "format": "csv",
            "zones": [{"zone_id": "z1", "floor_area_m2": 50}],
        }).encode()
        result_str = run_async(run_export_energy_model(FakeCtx(), args_bytes))
        result = json.loads(result_str)
        assert result.get("ok") is False or "reason" in result


# ---------------------------------------------------------------------------
# Oracle 14 — multi-zone: all zone IDs appear in gbXML
# ---------------------------------------------------------------------------

class TestMultiZoneGbxml:
    def test_all_zone_ids_in_gbxml(self):
        zones_data = [
            {"zone_id": "north_wing", "floor_area_m2": 120},
            {"zone_id": "south_wing", "floor_area_m2": 90},
            {"zone_id": "core",       "floor_area_m2": 60},
        ]
        args_bytes = json.dumps({
            "format": "gbxml",
            "building_name": "Multi Zone Building",
            "zones": zones_data,
        }).encode()
        result_str = run_async(run_export_energy_model(FakeCtx(), args_bytes))
        result = json.loads(result_str)
        assert result.get("n_zones") == 3
        content = result.get("content", "")
        for zd in zones_data:
            assert zd["zone_id"] in content, f"Zone {zd['zone_id']} not in gbXML"


# ---------------------------------------------------------------------------
# Oracle 15 — R-value / conductivity consistency in gbXML Material
# ---------------------------------------------------------------------------

class TestMaterialRValue:
    def test_wall_material_conductivity_consistent_with_u(self):
        """Material conductivity = 0.2 / R = 0.2 × U (for 0.2 m layer proxy)."""
        u_wall = 0.25  # W/(m²·K)
        r_wall = 1.0 / u_wall  # 4.0 m²K/W
        expected_k = 0.200 / r_wall  # 0.05 W/(mK)

        model = single_zone_model(wall_u=u_wall)
        xml_str = export_gbxml(model)
        # Find conductivity value in output
        assert f"{expected_k:.5f}" in xml_str, (
            f"Expected conductivity {expected_k:.5f} not found in gbXML material"
        )
