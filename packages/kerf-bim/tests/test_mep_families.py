"""
Tests for kerf_bim.mep_families — parametric MEP family definitions.

Covers:
  - All 10 MEP family definitions instantiate without error
  - Formula-driven derived parameters are computed correctly
  - Each family result dict has ifc_type + ifc_predefined_type
  - Each family result dict has at least one connector port
  - IFC type helpers (ifc_type_for_family, ifc_predefined_type_for_family)
  - connector_ports_for_family returns MEPPortDescriptor objects
  - Parameter overrides propagate through formulas
  - validate_family passes for all MEP families
  - Edge cases: zero-flow, max parameters
"""
from __future__ import annotations

import math
import pytest

from kerf_bim.mep_families import (
    AIR_DIFFUSER_FAMILY,
    AIR_GRILLE_FAMILY,
    DUCT_TEE_FAMILY,
    DUCT_ELBOW_FAMILY,
    DUCT_REDUCER_FAMILY,
    PIPE_VALVE_FAMILY,
    PIPE_PUMP_FAMILY,
    LUMINAIRE_FAMILY,
    SOCKET_OUTLET_FAMILY,
    JUNCTION_BOX_FAMILY,
    ALL_MEP_FAMILIES,
    MEPPortDescriptor,
    ConnectorPortKind,
    ifc_type_for_family,
    ifc_predefined_type_for_family,
    connector_ports_for_family,
)
from kerf_bim.family_editor import instantiate_family, validate_family


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(fam, **overrides):
    """Instantiate *fam* with *overrides* and return the result dict."""
    out = instantiate_family(fam, overrides or None)
    assert isinstance(out, dict), f"Expected dict, got {type(out)}"
    return out


# ---------------------------------------------------------------------------
# TestFamilyRegistration
# ---------------------------------------------------------------------------

class TestFamilyRegistration:
    def test_all_mep_families_count(self):
        assert len(ALL_MEP_FAMILIES) == 10

    def test_all_family_names_unique(self):
        names = [f.name for f in ALL_MEP_FAMILIES]
        assert len(names) == len(set(names))

    def test_all_families_have_valid_category(self):
        for fam in ALL_MEP_FAMILIES:
            assert fam.category in fam.VALID_CATEGORIES, (
                f"{fam.name}: invalid category '{fam.category}'"
            )

    def test_all_families_validate_cleanly(self):
        for fam in ALL_MEP_FAMILIES:
            errors = validate_family(fam)
            assert errors == [], f"{fam.name} validation errors: {errors}"


# ---------------------------------------------------------------------------
# TestAirDiffuser
# ---------------------------------------------------------------------------

class TestAirDiffuser:
    def test_default_instantiation(self):
        r = _result(AIR_DIFFUSER_FAMILY)
        assert r["ifc_type"] == "IfcAirTerminal"
        assert r["ifc_predefined_type"] == "DIFFUSER"

    def test_formula_neck_radius(self):
        r = _result(AIR_DIFFUSER_FAMILY, neck_size_mm=200.0)
        assert r["neck_radius_mm"] == pytest.approx(100.0)

    def test_formula_face_area(self):
        r = _result(AIR_DIFFUSER_FAMILY, face_size_mm=600.0)
        assert r["face_area_m2"] == pytest.approx(0.36, rel=1e-3)

    def test_formula_supply_velocity(self):
        # flow=20 l/s, face=600mm → 0.02 m³/s / 0.36 m² ≈ 0.0556 m/s
        r = _result(AIR_DIFFUSER_FAMILY, design_flow_ls=20.0, face_size_mm=600.0)
        assert r["supply_velocity_ms"] == pytest.approx(0.0556, rel=1e-2)

    def test_has_connector_port(self):
        r = _result(AIR_DIFFUSER_FAMILY)
        assert len(r["ports"]) >= 1
        port = r["ports"][0]
        assert port["kind"] == "SINK"
        assert port["medium"] == "air"

    def test_override_flow(self):
        r = _result(AIR_DIFFUSER_FAMILY, design_flow_ls=50.0, face_size_mm=600.0)
        # 50 l/s / 0.36 m² = 0.1389 m/s
        assert r["supply_velocity_ms"] == pytest.approx(0.1389, rel=1e-2)


# ---------------------------------------------------------------------------
# TestAirGrille
# ---------------------------------------------------------------------------

class TestAirGrille:
    def test_ifc_type(self):
        r = _result(AIR_GRILLE_FAMILY)
        assert r["ifc_type"] == "IfcAirTerminal"
        assert r["ifc_predefined_type"] == "GRILLE"

    def test_formula_face_area(self):
        r = _result(AIR_GRILLE_FAMILY, face_width_mm=600.0, face_height_mm=300.0)
        assert r["face_area_m2"] == pytest.approx(0.18, rel=1e-3)

    def test_formula_face_velocity(self):
        r = _result(AIR_GRILLE_FAMILY,
                    face_width_mm=600.0, face_height_mm=300.0, design_flow_ls=15.0)
        # 15 l/s / 0.18 m² ≈ 0.0833 m/s
        assert r["face_velocity_ms"] == pytest.approx(0.0833, rel=1e-2)

    def test_return_port_kind(self):
        r = _result(AIR_GRILLE_FAMILY)
        assert r["ports"][0]["kind"] == "SOURCE"

    def test_damper_flag(self):
        r = _result(AIR_GRILLE_FAMILY, has_damper=False)
        assert r["has_damper"] is False


# ---------------------------------------------------------------------------
# TestDuctTee
# ---------------------------------------------------------------------------

class TestDuctTee:
    def test_ifc_type(self):
        r = _result(DUCT_TEE_FAMILY)
        assert r["ifc_type"] == "IfcDuctFitting"
        assert r["ifc_predefined_type"] == "JUNCTION"

    def test_flow_balance_default_split(self):
        r = _result(DUCT_TEE_FAMILY, trunk_flow_ls=100.0, branch_split=0.5)
        assert r["branch1_flow_ls"] == pytest.approx(50.0)
        assert r["branch2_flow_ls"] == pytest.approx(50.0)

    def test_flow_balance_70_30(self):
        r = _result(DUCT_TEE_FAMILY, trunk_flow_ls=100.0, branch_split=0.7)
        assert r["branch1_flow_ls"] == pytest.approx(70.0)
        assert r["branch2_flow_ls"] == pytest.approx(30.0)

    def test_flow_conserved(self):
        r = _result(DUCT_TEE_FAMILY, trunk_flow_ls=80.0, branch_split=0.4)
        assert r["branch1_flow_ls"] + r["branch2_flow_ls"] == pytest.approx(80.0)

    def test_three_ports(self):
        r = _result(DUCT_TEE_FAMILY)
        assert len(r["ports"]) == 3

    def test_trunk_port_is_sink(self):
        r = _result(DUCT_TEE_FAMILY)
        trunk = r["ports"][0]
        assert trunk["kind"] == "SINK"
        assert trunk["name"] == "Trunk"

    def test_branch_ports_are_sources(self):
        r = _result(DUCT_TEE_FAMILY)
        assert r["ports"][1]["kind"] == "SOURCE"
        assert r["ports"][2]["kind"] == "SOURCE"


# ---------------------------------------------------------------------------
# TestDuctElbow
# ---------------------------------------------------------------------------

class TestDuctElbow:
    def test_ifc_type(self):
        r = _result(DUCT_ELBOW_FAMILY)
        assert r["ifc_type"] == "IfcDuctFitting"
        assert r["ifc_predefined_type"] == "BEND"

    def test_r_over_d_default(self):
        # radius=600, size=400 → r/D = 1.5
        r = _result(DUCT_ELBOW_FAMILY, radius_mm=600.0, size_mm=400.0)
        assert r["r_over_d"] == pytest.approx(1.5, rel=1e-3)

    def test_loss_coeff_90_deg(self):
        # C = 0.0447 * 90^0.5 / 1.5^1.22
        # 90^0.5 = 9.4868; 1.5^1.22 ≈ 1.625
        r = _result(DUCT_ELBOW_FAMILY, angle_deg=90.0, radius_mm=600.0, size_mm=400.0)
        expected = 0.0447 * math.sqrt(90) / (1.5 ** 1.22)
        assert r["smacna_loss_coefficient"] == pytest.approx(expected, rel=1e-2)

    def test_loss_coeff_decreases_with_larger_radius(self):
        r1 = _result(DUCT_ELBOW_FAMILY, angle_deg=90.0, radius_mm=400.0, size_mm=400.0)
        r2 = _result(DUCT_ELBOW_FAMILY, angle_deg=90.0, radius_mm=800.0, size_mm=400.0)
        assert r2["smacna_loss_coefficient"] < r1["smacna_loss_coefficient"]

    def test_two_ports(self):
        r = _result(DUCT_ELBOW_FAMILY)
        assert len(r["ports"]) == 2


# ---------------------------------------------------------------------------
# TestDuctReducer
# ---------------------------------------------------------------------------

class TestDuctReducer:
    def test_ifc_type(self):
        r = _result(DUCT_REDUCER_FAMILY)
        assert r["ifc_type"] == "IfcDuctFitting"
        assert r["ifc_predefined_type"] == "TRANSITION"

    def test_area_ratio_equal_sizes(self):
        r = _result(DUCT_REDUCER_FAMILY, inlet_size_mm=400.0, outlet_size_mm=400.0)
        assert r["area_ratio"] == pytest.approx(1.0, rel=1e-3)

    def test_area_ratio_half(self):
        # inlet_area = π*(200/1000)² = π*0.04
        # outlet_area = π*(100/1000)² = π*0.01 → ratio=0.25
        r = _result(DUCT_REDUCER_FAMILY, inlet_size_mm=400.0, outlet_size_mm=200.0)
        assert r["area_ratio"] == pytest.approx(0.25, rel=1e-3)

    def test_loss_coeff_zero_for_equal(self):
        r = _result(DUCT_REDUCER_FAMILY, inlet_size_mm=400.0, outlet_size_mm=400.0)
        assert r["loss_coefficient"] == pytest.approx(0.0, abs=1e-6)

    def test_loss_coeff_positive_for_reducer(self):
        r = _result(DUCT_REDUCER_FAMILY, inlet_size_mm=400.0, outlet_size_mm=200.0)
        assert r["loss_coefficient"] > 0.0

    def test_two_ports(self):
        r = _result(DUCT_REDUCER_FAMILY)
        assert len(r["ports"]) == 2


# ---------------------------------------------------------------------------
# TestPipeValve
# ---------------------------------------------------------------------------

class TestPipeValve:
    def test_ifc_type(self):
        r = _result(PIPE_VALVE_FAMILY)
        assert r["ifc_type"] == "IfcValve"
        assert r["ifc_predefined_type"] == "ISOLATING"

    def test_dp_at_1ms(self):
        # dp = kv * ρ * v² / 2 = 0.2 * 1000 * 1 / 2 = 100 Pa
        r = _result(PIPE_VALVE_FAMILY, kv_open=0.2)
        assert r["dp_at_1ms_pa"] == pytest.approx(100.0)

    def test_valve_medium_is_water(self):
        r = _result(PIPE_VALVE_FAMILY)
        for port in r["ports"]:
            assert port["medium"] == "water"

    def test_two_ports(self):
        r = _result(PIPE_VALVE_FAMILY)
        assert len(r["ports"]) == 2

    def test_dn_propagates_to_port(self):
        r = _result(PIPE_VALVE_FAMILY, dn_mm=80.0)
        for port in r["ports"]:
            assert port["size_mm"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# TestPipePump
# ---------------------------------------------------------------------------

class TestPipePump:
    def test_ifc_type(self):
        r = _result(PIPE_PUMP_FAMILY)
        assert r["ifc_type"] == "IfcPump"
        assert r["ifc_predefined_type"] == "CIRCULATOR"

    def test_efficiency_calculation(self):
        # hydraulic_pw = 30000 Pa * (2/1000 m³/s) = 60 W
        # efficiency = 60 / 250 = 0.24 → 24%
        r = _result(PIPE_PUMP_FAMILY,
                    design_flow_ls=2.0, design_head_pa=30000.0, motor_power_w=250.0)
        assert r["efficiency_pct"] == pytest.approx(24.0, rel=1e-2)

    def test_efficiency_capped_at_100(self):
        # Artificially low motor power → efficiency > 1 → capped to 1.0
        r = _result(PIPE_PUMP_FAMILY,
                    design_flow_ls=1000.0, design_head_pa=100000.0, motor_power_w=10.0)
        assert r["efficiency_pct"] == pytest.approx(100.0)

    def test_hydraulic_power(self):
        # P_h = 30000 * 0.002 = 60 W
        r = _result(PIPE_PUMP_FAMILY, design_flow_ls=2.0, design_head_pa=30000.0)
        assert r["hydraulic_power_w"] == pytest.approx(60.0)

    def test_two_ports(self):
        r = _result(PIPE_PUMP_FAMILY)
        assert len(r["ports"]) == 2

    def test_pump_port_medium_water(self):
        r = _result(PIPE_PUMP_FAMILY)
        for port in r["ports"]:
            assert port["medium"] == "water"


# ---------------------------------------------------------------------------
# TestLuminaire
# ---------------------------------------------------------------------------

class TestLuminaire:
    def test_ifc_type(self):
        r = _result(LUMINAIRE_FAMILY)
        assert r["ifc_type"] == "IfcLightFixture"
        assert r["ifc_predefined_type"] == "POINTSOURCE"

    def test_efficacy(self):
        r = _result(LUMINAIRE_FAMILY, lumens=4000.0, wattage_w=40.0)
        assert r["efficacy_lm_w"] == pytest.approx(100.0)

    def test_face_area(self):
        r = _result(LUMINAIRE_FAMILY, length_mm=1200.0, width_mm=300.0)
        assert r["face_area_m2"] == pytest.approx(0.36, rel=1e-3)

    def test_has_power_port(self):
        r = _result(LUMINAIRE_FAMILY)
        assert any(p["medium"] == "electrical" for p in r["ports"])

    def test_cct_passthrough(self):
        r = _result(LUMINAIRE_FAMILY, cct_k=3000.0)
        assert r["cct_k"] == pytest.approx(3000.0)


# ---------------------------------------------------------------------------
# TestSocketOutlet
# ---------------------------------------------------------------------------

class TestSocketOutlet:
    def test_ifc_type(self):
        r = _result(SOCKET_OUTLET_FAMILY)
        assert r["ifc_type"] == "IfcElectricDistributionBoard"

    def test_max_power(self):
        r = _result(SOCKET_OUTLET_FAMILY, voltage_v=230.0, current_a=13.0)
        assert r["max_power_w"] == pytest.approx(2990.0)

    def test_is_switched_default_true(self):
        r = _result(SOCKET_OUTLET_FAMILY)
        assert r["is_switched"] is True

    def test_electrical_port(self):
        r = _result(SOCKET_OUTLET_FAMILY)
        assert any(p["medium"] == "electrical" for p in r["ports"])


# ---------------------------------------------------------------------------
# TestJunctionBox
# ---------------------------------------------------------------------------

class TestJunctionBox:
    def test_ifc_type(self):
        r = _result(JUNCTION_BOX_FAMILY)
        assert r["ifc_type"] == "IfcJunctionBox"
        assert r["ifc_predefined_type"] == "POWER"

    def test_volume(self):
        r = _result(JUNCTION_BOX_FAMILY, width_mm=150.0, height_mm=150.0, depth_mm=70.0)
        # 150 * 150 * 70 / 1000 = 1575 cm³
        assert r["volume_cm3"] == pytest.approx(1575.0)

    def test_ip_rating_string(self):
        r = _result(JUNCTION_BOX_FAMILY, ip_rating=55.0)
        assert r["ip_rating_str"] == "IP55"

    def test_n_knockouts_ports(self):
        r = _result(JUNCTION_BOX_FAMILY, n_knockouts=4.0)
        assert len(r["ports"]) == 4

    def test_port_medium_electrical(self):
        r = _result(JUNCTION_BOX_FAMILY, n_knockouts=2.0)
        for port in r["ports"]:
            assert port["medium"] == "electrical"


# ---------------------------------------------------------------------------
# TestIFCHelpers
# ---------------------------------------------------------------------------

class TestIFCHelpers:
    def test_ifc_type_for_diffuser(self):
        t = ifc_type_for_family("Supply Air Diffuser")
        assert t == "IfcAirTerminal"

    def test_ifc_predefined_type_for_diffuser(self):
        pt = ifc_predefined_type_for_family("Supply Air Diffuser")
        assert pt == "DIFFUSER"

    def test_ifc_type_for_pump(self):
        assert ifc_type_for_family("Circulator Pump") == "IfcPump"

    def test_ifc_type_unknown_family(self):
        assert ifc_type_for_family("Nonexistent Family") is None

    def test_ifc_predefined_type_unknown_family(self):
        assert ifc_predefined_type_for_family("Nonexistent Family") is None

    def test_all_families_have_ifc_type(self):
        for fam in ALL_MEP_FAMILIES:
            t = ifc_type_for_family(fam.name)
            assert t is not None and t.startswith("Ifc"), (
                f"{fam.name}: ifc_type_for_family returned {t!r}"
            )


# ---------------------------------------------------------------------------
# TestConnectorPorts
# ---------------------------------------------------------------------------

class TestConnectorPorts:
    def test_diffuser_ports_returns_descriptors(self):
        ports = connector_ports_for_family("Supply Air Diffuser")
        assert len(ports) == 1
        assert isinstance(ports[0], MEPPortDescriptor)

    def test_tee_three_ports(self):
        ports = connector_ports_for_family("Duct Tee")
        assert len(ports) == 3

    def test_port_kind_values(self):
        ports = connector_ports_for_family("Supply Air Diffuser")
        assert ports[0].kind in (
            ConnectorPortKind.SINK,
            ConnectorPortKind.SOURCE,
            ConnectorPortKind.SOURCEANDSINK,
            ConnectorPortKind.NOTDEFINED,
        )

    def test_port_medium_air_for_diffuser(self):
        ports = connector_ports_for_family("Supply Air Diffuser")
        assert all(p.medium == "air" for p in ports)

    def test_port_medium_water_for_pump(self):
        ports = connector_ports_for_family("Circulator Pump")
        assert all(p.medium == "water" for p in ports)

    def test_port_medium_electrical_for_luminaire(self):
        ports = connector_ports_for_family("Recessed LED Luminaire")
        assert all(p.medium == "electrical" for p in ports)

    def test_unknown_family_returns_empty(self):
        ports = connector_ports_for_family("No Such Family")
        assert ports == []

    def test_with_param_overrides_neck_size(self):
        ports = connector_ports_for_family(
            "Supply Air Diffuser",
            {"neck_size_mm": 315.0},
        )
        assert ports[0].size_mm == pytest.approx(315.0)

    def test_junction_box_n_ports_override(self):
        ports = connector_ports_for_family("Junction Box", {"n_knockouts": 6.0})
        assert len(ports) == 6
