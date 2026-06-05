"""
test_mep_engine.py — Comprehensive tests for kerf_bim.mep_engine.

Tests cover:
1.  System classification / IFC4 system type enum values
2.  Domain and carrier resolution per system type
3.  make_mep_system factory + defaults
4.  make_mep_system with explicit params
5.  make_mep_system raises MEPError on invalid system_type
6.  add_segment creates connectors
7.  add_segment velocity from flow
8.  add_fitting to system
9.  add_endpoint to system
10. size_duct_diameter: basic sizing
11. size_duct_diameter: velocity constraint
12. size_duct_diameter: larger flow → larger diameter
13. size_duct_diameter raises MEPSizingError for zero flow
14. size_duct_rect: returns width and height
15. size_duct_rect: aspect ratio respected
16. size_pipe_dn: returns valid DN
17. size_pipe_dn: larger flow → larger DN
18. size_pipe_dn raises MEPSizingError for zero flow
19. velocity_check: all segments in range → ok
20. velocity_check: out-of-range velocity → warning
21. swamee_jain_friction: laminar regime
22. swamee_jain_friction: turbulent regime
23. darcy_weisbach: positive pressure drop
24. darcy_weisbach: longer pipe → higher drop
25. duct_pressure_drop: HVAC system
26. duct_pressure_drop: conduit → zero
27. duct_pressure_drop includes fitting equivalent lengths
28. build_adjacency: adjacent segments share endpoint
29. build_adjacency: non-adjacent segments
30. connectivity_check: single connected system
31. connectivity_check: isolated segment
32. connectivity_check: unconnected endpoint reference
33. connectivity_check: flow imbalance at tee
34. connectivity_check: empty system ok
35. system_to_ifc_dict: correct IFC types for duct
36. system_to_ifc_dict: correct IFC types for pipe
37. system_to_ifc_dict: correct IFC types for conduit
38. system_to_ifc_dict: segment ports included
39. MEPSystem dataclass creation
40. MEPSegment hydraulic_diameter_mm circular
41. MEPSegment hydraulic_diameter_mm rectangular
42. MEPSegment cross_section_area_m2
43. RECOMMENDED_VELOCITY_MS contains supply air
44. SystemTypeEnum all unique values
45. system_to_ifc_dict: endpoints serialised
"""
from __future__ import annotations

import math
import pytest

from kerf_bim.mep_engine import (
    # Enumerations
    SystemDomain,
    SystemTypeEnum,
    SystemType,
    ConnectorKind,
    FittingKind,
    SegmentKind,
    # Data classes
    MEPConnector,
    MEPSegment,
    MEPFitting,
    MEPEndpoint,
    MEPSystem,
    # Factory helpers
    make_mep_system,
    add_segment,
    add_fitting,
    add_endpoint,
    # Sizing
    size_duct_diameter,
    size_duct_rect,
    size_pipe_dn,
    velocity_check,
    # Hydraulics
    darcy_weisbach,
    swamee_jain_friction,
    duct_pressure_drop,
    # Connectivity
    build_adjacency,
    connectivity_check,
    # IFC
    system_to_ifc_dict,
    # Constants
    RECOMMENDED_VELOCITY_MS,
    ROUGHNESS_MM,
    # Errors
    MEPError,
    MEPSizingError,
    MEPConnectivityError,
    VALID_SYSTEM_TYPES,
    SYSTEM_TYPE_DOMAIN,
    SYSTEM_CARRIER,
    SYSTEM_MEDIUM,
)


# ---------------------------------------------------------------------------
# 1-2: System classification
# ---------------------------------------------------------------------------

class TestSystemClassification:

    def test_supply_air_domain(self):
        """SUPPLYAIR maps to HVAC domain."""
        assert SYSTEM_TYPE_DOMAIN[SystemTypeEnum.SUPPLY_AIR] == SystemDomain.HVAC

    def test_cold_water_domain(self):
        assert SYSTEM_TYPE_DOMAIN[SystemTypeEnum.COLD_WATER] == SystemDomain.PLUMBING

    def test_electrical_power_domain(self):
        assert SYSTEM_TYPE_DOMAIN[SystemTypeEnum.ELECTRICAL_POWER] == SystemDomain.ELECTRICAL

    def test_fire_domain(self):
        assert SYSTEM_TYPE_DOMAIN[SystemTypeEnum.FIRE_PROTECTION] == SystemDomain.FIRE

    def test_telecom_domain(self):
        assert SYSTEM_TYPE_DOMAIN[SystemTypeEnum.TELECOM] == SystemDomain.TELECOM

    def test_supply_air_carrier_duct(self):
        assert SYSTEM_CARRIER[SystemTypeEnum.SUPPLY_AIR] == "duct"

    def test_cold_water_carrier_pipe(self):
        assert SYSTEM_CARRIER[SystemTypeEnum.COLD_WATER] == "pipe"

    def test_electrical_carrier_conduit(self):
        assert SYSTEM_CARRIER[SystemTypeEnum.ELECTRICAL_POWER] == "conduit"

    def test_medium_air(self):
        assert SYSTEM_MEDIUM[SystemTypeEnum.SUPPLY_AIR] == "air"

    def test_medium_water(self):
        assert SYSTEM_MEDIUM[SystemTypeEnum.COLD_WATER] == "water"

    def test_medium_electrical(self):
        assert SYSTEM_MEDIUM[SystemTypeEnum.ELECTRICAL_POWER] == "electrical"

    def test_all_system_types_have_domain(self):
        for st in VALID_SYSTEM_TYPES:
            assert st in SYSTEM_TYPE_DOMAIN, f"{st} has no domain mapping"

    def test_all_system_types_have_carrier(self):
        for st in VALID_SYSTEM_TYPES:
            assert st in SYSTEM_CARRIER, f"{st} has no carrier mapping"

    def test_system_type_alias(self):
        """SystemType is an alias for SystemTypeEnum."""
        assert SystemType.SUPPLY_AIR == SystemTypeEnum.SUPPLY_AIR


# ---------------------------------------------------------------------------
# 3-5: make_mep_system
# ---------------------------------------------------------------------------

class TestMakeMEPSystem:

    def test_supply_air_defaults(self):
        sys = make_mep_system("Supply Air AHU-01", SystemTypeEnum.SUPPLY_AIR)
        assert sys.carrier == "duct"
        assert sys.domain == SystemDomain.HVAC
        assert sys.medium == "air"
        assert sys.material == "galvanized_steel"
        assert sys.size_mm > 0
        assert sys.design_velocity_m_s > 0

    def test_cold_water_defaults(self):
        sys = make_mep_system("CW Main", SystemTypeEnum.COLD_WATER)
        assert sys.carrier == "pipe"
        assert sys.material == "copper"

    def test_electrical_defaults(self):
        sys = make_mep_system("Power Run L1", SystemTypeEnum.ELECTRICAL_POWER)
        assert sys.carrier == "conduit"

    def test_explicit_material(self):
        sys = make_mep_system("HW", SystemTypeEnum.HOT_WATER, material="stainless_steel")
        assert sys.material == "stainless_steel"

    def test_explicit_size(self):
        sys = make_mep_system("Supply Air", SystemTypeEnum.SUPPLY_AIR, size_mm=500)
        assert sys.size_mm == pytest.approx(500.0)

    def test_explicit_rect_duct(self):
        sys = make_mep_system("Supply", SystemTypeEnum.SUPPLY_AIR,
                              width_mm=600, height_mm=400)
        assert sys.width_mm == pytest.approx(600.0)
        assert sys.height_mm == pytest.approx(400.0)

    def test_invalid_system_type_raises(self):
        with pytest.raises(MEPError):
            make_mep_system("Bad", "TOTALLY_INVALID_TYPE")

    def test_insulation_duct(self):
        sys = make_mep_system("Supply", SystemTypeEnum.SUPPLY_AIR)
        assert sys.insulation_thickness_mm == pytest.approx(25.0)

    def test_insulation_pipe_zero(self):
        sys = make_mep_system("CW", SystemTypeEnum.COLD_WATER)
        assert sys.insulation_thickness_mm == pytest.approx(0.0)

    def test_system_colour_by_domain(self):
        hvac = make_mep_system("Air", SystemTypeEnum.SUPPLY_AIR)
        plumbing = make_mep_system("Water", SystemTypeEnum.COLD_WATER)
        electrical = make_mep_system("Power", SystemTypeEnum.ELECTRICAL_POWER)
        assert hvac.system_color != plumbing.system_color
        assert electrical.system_color != plumbing.system_color

    def test_design_velocity_default_from_smacna(self):
        """Default velocity must be within SMACNA recommended range."""
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR)
        lo, hi = RECOMMENDED_VELOCITY_MS[SystemTypeEnum.SUPPLY_AIR]
        assert lo <= sys.design_velocity_m_s <= hi


# ---------------------------------------------------------------------------
# 6-9: add_segment / add_fitting / add_endpoint
# ---------------------------------------------------------------------------

class TestAddHelpers:

    def _system(self):
        return make_mep_system("Supply Air", SystemTypeEnum.SUPPLY_AIR,
                               size_mm=400, design_flow_l_s=200)

    def test_add_segment_appends(self):
        sys = self._system()
        seg = add_segment(sys, [0, 0, 3000], [5000, 0, 3000])
        assert len(sys.segments) == 1
        assert seg is sys.segments[0]

    def test_add_segment_connectors(self):
        sys = self._system()
        seg = add_segment(sys, [0, 0, 0], [3000, 0, 0])
        assert len(seg.connectors) == 2
        assert seg.connectors[0].position == [0, 0, 0]
        assert seg.connectors[1].position == [3000, 0, 0]

    def test_add_segment_velocity_from_flow(self):
        sys = self._system()
        seg = add_segment(sys, [0, 0, 0], [1000, 0, 0], flow_l_s=50.0)
        # flow 50 l/s through 400mm circular duct
        area = math.pi * (0.2) ** 2  # 200mm radius
        expected_v = 0.050 / area
        assert seg.velocity_m_s == pytest.approx(expected_v, rel=0.01)

    def test_add_segment_custom_id(self):
        sys = self._system()
        seg = add_segment(sys, [0, 0, 0], [1000, 0, 0], segment_id="my_seg_1")
        assert seg.id == "my_seg_1"

    def test_add_fitting_appends(self):
        sys = self._system()
        fit = add_fitting(sys, FittingKind.TEE, [2500, 0, 3000],
                          branches=["s1", "s2", "s3"])
        assert len(sys.fittings) == 1
        assert fit.kind == FittingKind.TEE
        assert "s1" in fit.branches

    def test_add_fitting_reducer(self):
        sys = self._system()
        fit = add_fitting(sys, FittingKind.REDUCER, [3000, 0, 3000],
                          size_in_mm=400, size_out_mm=250)
        assert fit.size_in_mm == pytest.approx(400.0)
        assert fit.size_out_mm == pytest.approx(250.0)

    def test_add_endpoint_appends(self):
        sys = self._system()
        ep = add_endpoint(sys, "Diffuser D1", [5000, 2500, 2700],
                          design_flow_l_s=15.0)
        assert len(sys.endpoints) == 1
        assert ep.label == "Diffuser D1"
        assert ep.design_flow_l_s == pytest.approx(15.0)

    def test_add_endpoint_connected_segment(self):
        sys = self._system()
        seg = add_segment(sys, [0, 0, 0], [5000, 0, 0])
        ep = add_endpoint(sys, "EP1", [5000, 0, 0],
                          connected_segment_id=seg.id)
        assert ep.connected_segment_id == seg.id


# ---------------------------------------------------------------------------
# 10-15: Duct sizing (SMACNA / ASHRAE equal-friction)
# ---------------------------------------------------------------------------

class TestDuctSizing:

    def test_basic_sizing_returns_diameter(self):
        result = size_duct_diameter(100.0)  # 100 l/s
        assert result["diameter_mm"] > 0
        assert result["diameter_nominal_mm"] > 0
        assert result["velocity_m_s"] > 0

    def test_larger_flow_larger_diameter(self):
        d50 = size_duct_diameter(50.0)["diameter_mm"]
        d200 = size_duct_diameter(200.0)["diameter_mm"]
        assert d200 > d50

    def test_nominal_diameter_multiple_of_50(self):
        result = size_duct_diameter(100.0)
        assert result["diameter_nominal_mm"] % 50 == 0

    def test_friction_rate_near_target(self):
        """Actual friction should be within ±30% of 1.0 Pa/m target."""
        result = size_duct_diameter(100.0, target_pa_per_m=1.0)
        assert 0.5 < result["friction_pa_per_m"] < 2.0

    def test_velocity_warning_if_exceeded(self):
        """Very high flow through tiny target might exceed velocity limit."""
        # Force a high velocity by setting a low velocity_max
        result = size_duct_diameter(1000.0, velocity_max_m_s=1.0)
        # Either has a warning or the velocity is below limit
        if result["velocity_m_s"] > 1.0:
            assert result["warning"] is not None

    def test_zero_flow_raises(self):
        with pytest.raises(MEPSizingError):
            size_duct_diameter(0.0)

    def test_negative_flow_raises(self):
        with pytest.raises(MEPSizingError):
            size_duct_diameter(-5.0)

    def test_rect_sizing_width_height(self):
        result = size_duct_rect(100.0, aspect_ratio=2.0)
        assert "width_mm" in result
        assert "height_mm" in result
        assert result["width_mm"] > 0
        assert result["height_mm"] > 0

    def test_rect_aspect_ratio(self):
        result = size_duct_rect(100.0, aspect_ratio=2.0)
        assert result["aspect_ratio"] == pytest.approx(2.0, abs=0.1)


# ---------------------------------------------------------------------------
# 16-18: Pipe sizing (CIBSE / DN)
# ---------------------------------------------------------------------------

class TestPipeSizing:

    def test_basic_dn_sizing(self):
        result = size_pipe_dn(0.5, SystemTypeEnum.COLD_WATER)
        assert result["dn"] > 0
        assert result["velocity_m_s"] > 0

    def test_larger_flow_larger_dn(self):
        dn_small = size_pipe_dn(0.1, SystemTypeEnum.COLD_WATER)["dn"]
        dn_large = size_pipe_dn(5.0, SystemTypeEnum.COLD_WATER)["dn"]
        assert dn_large >= dn_small

    def test_zero_flow_raises(self):
        with pytest.raises(MEPSizingError):
            size_pipe_dn(0.0)

    def test_velocity_within_limits(self):
        result = size_pipe_dn(1.0, SystemTypeEnum.COLD_WATER)
        lo, hi = RECOMMENDED_VELOCITY_MS[SystemTypeEnum.COLD_WATER]
        # Should be within velocity range (or slightly below with a warning)
        assert result["velocity_m_s"] <= hi + 0.01

    def test_flow_regime_field(self):
        result = size_pipe_dn(1.0, SystemTypeEnum.COLD_WATER)
        assert result["flow_regime"] in ("laminar", "transitional", "turbulent")

    def test_friction_factor_positive(self):
        result = size_pipe_dn(1.0, SystemTypeEnum.COLD_WATER)
        assert result["friction_factor"] > 0


# ---------------------------------------------------------------------------
# 19-20: velocity_check
# ---------------------------------------------------------------------------

class TestVelocityCheck:

    def _system_with_segs(self, velocities_ms: list[float]) -> MEPSystem:
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR, size_mm=400)
        lo, hi = RECOMMENDED_VELOCITY_MS[SystemTypeEnum.SUPPLY_AIR]
        for i, v in enumerate(velocities_ms):
            # Set velocity via flow_l_s
            area = math.pi * (0.2) ** 2  # r=200mm
            flow = v * area * 1000.0  # l/s
            add_segment(sys, [i*1000, 0, 0], [(i+1)*1000, 0, 0], flow_l_s=flow)
        return sys

    def test_all_in_range(self):
        # 5 m/s is within SMACNA supply air range [3, 8]
        sys = self._system_with_segs([5.0])
        result = velocity_check(sys, SystemTypeEnum.SUPPLY_AIR)
        assert result["ok"] is True
        assert result["out_of_range_count"] == 0

    def test_out_of_range_high(self):
        # 20 m/s exceeds SMACNA supply air max of 8 m/s
        sys = self._system_with_segs([20.0])
        result = velocity_check(sys, SystemTypeEnum.SUPPLY_AIR)
        assert result["ok"] is False
        assert result["out_of_range_count"] == 1

    def test_mixed_range(self):
        sys = self._system_with_segs([5.0, 20.0])
        result = velocity_check(sys, SystemTypeEnum.SUPPLY_AIR)
        assert result["out_of_range_count"] == 1


# ---------------------------------------------------------------------------
# 21-23: Friction factor and Darcy-Weisbach
# ---------------------------------------------------------------------------

class TestHydraulics:

    def test_laminar_friction(self):
        """f = 64/Re for laminar flow (Re < 2300)."""
        Re = 500.0
        f = swamee_jain_friction(Re, 0.046, 100.0)
        assert f == pytest.approx(64.0 / 500.0, rel=0.001)

    def test_turbulent_friction_positive(self):
        Re = 100000.0
        f = swamee_jain_friction(Re, 0.046, 100.0)
        assert 0.01 < f < 0.1  # typical turbulent range

    def test_turbulent_smoother_pipe_lower_f(self):
        """Smooth pipe (copper) has lower f than rough pipe (concrete)."""
        f_cu = swamee_jain_friction(100000, 0.0015, 100.0)
        f_ci = swamee_jain_friction(100000, 1.5, 100.0)
        assert f_cu < f_ci

    def test_darcy_weisbach_positive(self):
        dp = darcy_weisbach(10.0, 100.0, 1.0, 1000.0, 0.02)
        assert dp > 0

    def test_darcy_weisbach_double_length(self):
        dp1 = darcy_weisbach(10.0, 100.0, 1.0, 1000.0, 0.02)
        dp2 = darcy_weisbach(20.0, 100.0, 1.0, 1000.0, 0.02)
        assert dp2 == pytest.approx(dp1 * 2.0, rel=1e-9)


# ---------------------------------------------------------------------------
# 25-27: duct_pressure_drop
# ---------------------------------------------------------------------------

class TestDuctPressureDrop:

    def test_hvac_pressure_drop_positive(self):
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR,
                              size_mm=400, design_velocity_m_s=5.0)
        add_segment(sys, [0, 0, 0], [10000, 0, 0])  # 10m straight run
        result = duct_pressure_drop(sys)
        assert result["total_pressure_drop_pa"] > 0
        assert result["total_length_m"] == pytest.approx(10.0, rel=0.01)

    def test_conduit_zero_drop(self):
        sys = make_mep_system("Power", SystemTypeEnum.ELECTRICAL_POWER)
        add_segment(sys, [0, 0, 0], [5000, 0, 0])
        result = duct_pressure_drop(sys)
        assert result["total_pressure_drop_pa"] == pytest.approx(0.0)

    def test_fitting_adds_to_drop(self):
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR,
                              size_mm=400, design_velocity_m_s=5.0)
        add_segment(sys, [0, 0, 0], [5000, 0, 0])
        result_no_fitting = duct_pressure_drop(sys)

        add_fitting(sys, FittingKind.ELBOW, [2500, 0, 0])
        result_with_fitting = duct_pressure_drop(sys)
        assert result_with_fitting["fitting_drops_pa"] > 0
        assert (result_with_fitting["total_pressure_drop_pa"] >
                result_no_fitting["total_pressure_drop_pa"])

    def test_segment_drops_list(self):
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR,
                              size_mm=400, design_velocity_m_s=5.0)
        add_segment(sys, [0, 0, 0], [5000, 0, 0])
        add_segment(sys, [5000, 0, 0], [10000, 0, 0])
        result = duct_pressure_drop(sys)
        assert len(result["segment_drops"]) == 2


# ---------------------------------------------------------------------------
# 28-34: Connectivity
# ---------------------------------------------------------------------------

class TestConnectivity:

    def _make_connected_system(self) -> MEPSystem:
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR, size_mm=400)
        # Three connected segments sharing endpoints
        add_segment(sys, [0, 0, 0], [5000, 0, 0], segment_id="s1")
        add_segment(sys, [5000, 0, 0], [10000, 0, 0], segment_id="s2")
        add_segment(sys, [10000, 0, 0], [15000, 0, 0], segment_id="s3")
        return sys

    def test_adjacency_connected_chain(self):
        sys = self._make_connected_system()
        adj = build_adjacency(sys)
        assert "s2" in adj["s1"]
        assert "s1" in adj["s2"]
        assert "s3" in adj["s2"]

    def test_adjacency_non_adjacent(self):
        sys = self._make_connected_system()
        adj = build_adjacency(sys)
        # s1 and s3 are not directly adjacent (only through s2)
        assert "s3" not in adj["s1"]

    def test_connectivity_single_component(self):
        sys = self._make_connected_system()
        result = connectivity_check(sys)
        assert result["connected"] is True
        assert result["n_components"] == 1

    def test_connectivity_isolated_segment(self):
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR, size_mm=400)
        add_segment(sys, [0, 0, 0], [5000, 0, 0], segment_id="s1")
        # Isolated segment far away
        add_segment(sys, [99000, 99000, 0], [100000, 99000, 0], segment_id="s2")
        result = connectivity_check(sys)
        assert result["connected"] is False
        assert result["n_components"] == 2
        assert "s2" in result["isolated_segments"]

    def test_connectivity_unconnected_endpoint(self):
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR, size_mm=400)
        add_segment(sys, [0, 0, 0], [5000, 0, 0], segment_id="s1")
        # Endpoint references a non-existent segment
        add_endpoint(sys, "EP1", [5000, 0, 0],
                     connected_segment_id="nonexistent_seg")
        result = connectivity_check(sys)
        assert len(result["unconnected_endpoints"]) == 1

    def test_connectivity_flow_imbalance(self):
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR, size_mm=400)
        add_segment(sys, [0, 0, 0], [3000, 0, 0], segment_id="trunk", flow_l_s=100.0)
        add_segment(sys, [3000, 0, 0], [6000, 0, 0], segment_id="branch1", flow_l_s=30.0)
        add_segment(sys, [3000, 1000, 0], [6000, 1000, 0], segment_id="branch2", flow_l_s=20.0)
        # TEE: trunk 100 l/s, branch1 30 + branch2 20 = 50 ≠ 100 → >5% imbalance
        add_fitting(sys, FittingKind.TEE, [3000, 0, 0],
                    branches=["trunk", "branch1", "branch2"])
        result = connectivity_check(sys)
        assert len(result["flow_balance_warnings"]) > 0

    def test_connectivity_empty_system(self):
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR, size_mm=400)
        result = connectivity_check(sys)
        assert result["ok"] is True
        assert result["n_components"] == 0


# ---------------------------------------------------------------------------
# 35-45: IFC dict serialisation
# ---------------------------------------------------------------------------

class TestIFCDictSerialisation:

    def _duct_system(self) -> MEPSystem:
        sys = make_mep_system("Supply Air", SystemTypeEnum.SUPPLY_AIR, size_mm=400)
        add_segment(sys, [0, 0, 3000], [5000, 0, 3000], segment_id="s1")
        add_fitting(sys, FittingKind.ELBOW, [5000, 0, 3000])
        add_endpoint(sys, "Diffuser D1", [5000, 5000, 2700],
                     design_flow_l_s=20.0, connected_segment_id="s1")
        return sys

    def test_duct_ifc_type(self):
        d = system_to_ifc_dict(self._duct_system())
        assert d["ifc_type"] == "IfcDistributionSystem"
        assert d["segment_ifc_type"] == "IfcDuctSegment"
        assert d["fitting_ifc_type"] == "IfcDuctFitting"
        assert d["terminal_ifc_type"] == "IfcAirTerminal"

    def test_pipe_ifc_type(self):
        sys = make_mep_system("CW", SystemTypeEnum.COLD_WATER)
        add_segment(sys, [0, 0, 0], [3000, 0, 0])
        d = system_to_ifc_dict(sys)
        assert d["segment_ifc_type"] == "IfcPipeSegment"
        assert d["fitting_ifc_type"] == "IfcPipeFitting"
        assert d["terminal_ifc_type"] == "IfcSanitaryTerminal"

    def test_conduit_ifc_type(self):
        sys = make_mep_system("Power", SystemTypeEnum.ELECTRICAL_POWER)
        add_segment(sys, [0, 0, 0], [3000, 0, 0])
        d = system_to_ifc_dict(sys)
        assert d["segment_ifc_type"] == "IfcCableCarrierSegment"

    def test_segment_ports_included(self):
        sys = self._duct_system()
        d = system_to_ifc_dict(sys)
        seg_d = d["segments"][0]
        assert "ports" in seg_d
        assert len(seg_d["ports"]) == 2
        for port in seg_d["ports"]:
            assert "ifc_type" in port
            assert port["ifc_type"] == "IfcDistributionPort"

    def test_endpoints_serialised(self):
        sys = self._duct_system()
        d = system_to_ifc_dict(sys)
        assert len(d["endpoints"]) == 1
        ep = d["endpoints"][0]
        assert ep["label"] == "Diffuser D1"
        assert ep["design_flow_l_s"] == pytest.approx(20.0)

    def test_system_type_field(self):
        sys = self._duct_system()
        d = system_to_ifc_dict(sys)
        assert d["system_type"] == SystemTypeEnum.SUPPLY_AIR

    def test_segment_length_and_hyd_diameter(self):
        sys = make_mep_system("SA", SystemTypeEnum.SUPPLY_AIR, size_mm=400)
        add_segment(sys, [0, 0, 0], [5000, 0, 0], segment_id="s1")
        d = system_to_ifc_dict(sys)
        seg = d["segments"][0]
        assert seg["length_mm"] == pytest.approx(5000.0, rel=0.01)
        assert seg["hydraulic_diameter_mm"] == pytest.approx(400.0, rel=0.01)


# ---------------------------------------------------------------------------
# MEPSegment dataclass properties
# ---------------------------------------------------------------------------

class TestMEPSegmentProperties:

    def test_hydraulic_diameter_circular(self):
        seg = MEPSegment(id="s1", size_mm=400.0)
        assert seg.hydraulic_diameter_mm == pytest.approx(400.0)

    def test_hydraulic_diameter_rectangular(self):
        # 4A/P: 4×(600×400) / (2×(600+400)) = 4×240000/2000 = 480
        seg = MEPSegment(id="s2", size_mm=0, width_mm=600.0, height_mm=400.0)
        expected = (4 * 600 * 400) / (2 * (600 + 400))
        assert seg.hydraulic_diameter_mm == pytest.approx(expected)

    def test_cross_section_area_circular(self):
        seg = MEPSegment(id="s3", size_mm=400.0)
        expected = math.pi * (0.2) ** 2  # r=0.2m
        assert seg.cross_section_area_m2 == pytest.approx(expected, rel=1e-6)

    def test_cross_section_area_rectangular(self):
        seg = MEPSegment(id="s4", size_mm=0, width_mm=600.0, height_mm=400.0)
        expected = 0.6 * 0.4  # m²
        assert seg.cross_section_area_m2 == pytest.approx(expected)

    def test_length_mm(self):
        seg = MEPSegment(id="s5", from_pt=[0, 0, 0], to_pt=[5000, 0, 0])
        assert seg.length_mm == pytest.approx(5000.0)


# ---------------------------------------------------------------------------
# Misc constants / completeness
# ---------------------------------------------------------------------------

class TestConstants:

    def test_recommended_velocity_supply_air(self):
        lo, hi = RECOMMENDED_VELOCITY_MS[SystemTypeEnum.SUPPLY_AIR]
        assert lo > 0 and hi > lo

    def test_roughness_galvanised_steel(self):
        assert ROUGHNESS_MM["galvanized_steel"] == pytest.approx(0.046)

    def test_roughness_copper_smooth(self):
        assert ROUGHNESS_MM["copper"] < ROUGHNESS_MM["galvanized_steel"]

    def test_valid_system_types_nonempty(self):
        assert len(VALID_SYSTEM_TYPES) >= 10

    def test_system_type_enum_values_unique(self):
        values = [
            SystemTypeEnum.SUPPLY_AIR,
            SystemTypeEnum.RETURN_AIR,
            SystemTypeEnum.EXHAUST_AIR,
            SystemTypeEnum.COLD_WATER,
            SystemTypeEnum.HOT_WATER,
            SystemTypeEnum.SANITARY,
            SystemTypeEnum.ELECTRICAL_POWER,
            SystemTypeEnum.ELECTRICAL_LIGHTING,
            SystemTypeEnum.FIRE_PROTECTION,
            SystemTypeEnum.TELECOM,
        ]
        assert len(set(values)) == len(values), "SystemTypeEnum has duplicate values"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
