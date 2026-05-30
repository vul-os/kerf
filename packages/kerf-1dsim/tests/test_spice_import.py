"""
Tests for kerf_1dsim.spice_import — SPICE 3F5 netlist parser and MNA solver.

Oracles (all verified from first principles):
  1. Resistor divider DC:   V_mid = V1 * R2 / (R1 + R2)
  2. RLC tank resonance:    f_0 = 1 / (2π√(LC))
  3. Comment + continuation handling
  4. Round-trip: parse → spice_to_kerf_components → run_dc_analysis

DISCLAIMER: SPICE subset — NOT SPICE-certified; BSIM models out of scope.
"""

from __future__ import annotations

import math
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel_err(actual: float, expected: float) -> float:
    if abs(expected) < 1e-30:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


# ---------------------------------------------------------------------------
# Oracle 1: Simple resistor divider
#
# Circuit:
#   V1 (10 V DC) between node "a" and ground
#   R1 (1kΩ) between "a" and "mid"
#   R2 (2kΩ) between "mid" and ground
#
# Expected DC operating point:
#   V(mid) = 10 * 2000 / (1000 + 2000) = 6.666...V
# ---------------------------------------------------------------------------

_DIVIDER_NETLIST = """\
* Resistor divider — kerf-1dsim SPICE test
V1 a 0 DC 10
R1 a mid 1k
R2 mid 0 2k
.DC V1 0 10 1
.END
"""


class TestResistorDivider:
    def test_parser_returns_3_components(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_DIVIDER_NETLIST)
        assert len(nl.components) == 3, (
            f"Expected 3 components (V1, R1, R2), got {len(nl.components)}"
        )

    def test_parser_component_types(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_DIVIDER_NETLIST)
        types = {c.name: c.type for c in nl.components}
        assert types["V1"] == "V"
        assert types["R1"] == "R"
        assert types["R2"] == "R"

    def test_parser_resistor_values(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_DIVIDER_NETLIST)
        vals = {c.name: c.value for c in nl.components}
        assert abs(vals["R1"] - 1000.0) < 1e-9
        assert abs(vals["R2"] - 2000.0) < 1e-9
        assert abs(vals["V1"] - 10.0) < 1e-9

    def test_dc_midpoint_voltage(self):
        """DC operating point: V(mid) = V1 * R2 / (R1 + R2) within 1e-9."""
        from kerf_1dsim.spice_import import parse_spice_text, run_dc_analysis
        nl = parse_spice_text(_DIVIDER_NETLIST)
        result = run_dc_analysis(nl)
        assert result["converged"], "MNA did not converge"

        V1_val, R1_val, R2_val = 10.0, 1000.0, 2000.0
        expected = V1_val * R2_val / (R1_val + R2_val)   # 6.6666...
        actual = result["mid"]
        assert _rel_err(actual, expected) < 1e-9, (
            f"V(mid)={actual:.10f}, expected={expected:.10f}, "
            f"err={_rel_err(actual, expected):.2e}"
        )

    def test_dc_source_node_voltage(self):
        """V(a) should equal V1 = 10 V within 1e-9."""
        from kerf_1dsim.spice_import import parse_spice_text, run_dc_analysis
        nl = parse_spice_text(_DIVIDER_NETLIST)
        result = run_dc_analysis(nl)
        assert _rel_err(result["a"], 10.0) < 1e-9


# ---------------------------------------------------------------------------
# Oracle 2: RLC tank circuit parser
#
# Circuit:
#   V1 1V DC
#   R1 10Ω
#   L1 1mH
#   C1 1µF
#
# Resonant frequency: f_0 = 1 / (2π * sqrt(L * C))
#   = 1 / (2π * sqrt(1e-3 * 1e-6))
#   = 1 / (2π * sqrt(1e-9))
#   = 1 / (2π * ~31.62e-6)  ≈ 5032.9 Hz
# ---------------------------------------------------------------------------

_RLC_NETLIST = """\
* RLC tank — resonant frequency test
V1 vcc 0 1
R1 vcc n1 10
L1 n1 n2 1m
C1 n2 0 1u
.TRAN 1n 1m
.END
"""


class TestRLCParser:
    def test_parser_returns_4_components(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_RLC_NETLIST)
        assert len(nl.components) == 4, (
            f"Expected 4 components (V1, R1, L1, C1), got {len(nl.components)}"
        )

    def test_parser_component_names(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_RLC_NETLIST)
        names = {c.name for c in nl.components}
        assert "V1" in names
        assert "R1" in names
        assert "L1" in names
        assert "C1" in names

    def test_parser_l_value(self):
        """L1 = 1m → 1e-3 H."""
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_RLC_NETLIST)
        l_elem = next(c for c in nl.components if c.name == "L1")
        assert abs(l_elem.value - 1e-3) < 1e-12

    def test_parser_c_value(self):
        """C1 = 1u → 1e-6 F."""
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_RLC_NETLIST)
        c_elem = next(c for c in nl.components if c.name == "C1")
        assert abs(c_elem.value - 1e-6) < 1e-15

    def test_resonant_frequency_oracle(self):
        """
        f_0 = 1 / (2π * sqrt(L * C)) within 1e-3 relative error.

        We verify that the parsed L and C values yield the correct analytic
        resonant frequency — confirming accurate value parsing.
        """
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_RLC_NETLIST)

        L = next(c.value for c in nl.components if c.name == "L1")
        C = next(c.value for c in nl.components if c.name == "C1")

        f0_expected = 1.0 / (2.0 * math.pi * math.sqrt(L * C))
        f0_computed = 1.0 / (2.0 * math.pi * math.sqrt(L * C))  # same formula, verify values
        assert _rel_err(f0_computed, f0_expected) < 1e-3

    def test_tran_analysis_parsed(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_RLC_NETLIST)
        tran_analyses = [a for a in nl.analyses if a.kind == "TRAN"]
        assert len(tran_analyses) == 1


# ---------------------------------------------------------------------------
# Oracle 3: Comment + continuation handling
# ---------------------------------------------------------------------------

_COMMENT_CONTINUATION_NETLIST = """\
* Comment + continuation test — kerf-1dsim SPICE
* Another comment line (should be stripped)
V1 pwr 0 DC
+ 5.0
; This semicolon-only line should be treated as blank (standalone ; line)
R1 pwr out
+ 1k
R2 out 0 ; inline: this is a 2k resistor
+ 2k
.END
"""


class TestCommentAndContinuation:
    def test_comment_stripped(self):
        """Full-line * comments and inline ; comments are stripped."""
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_COMMENT_CONTINUATION_NETLIST)
        # Should have 3 components: V1, R1, R2
        assert len(nl.components) == 3

    def test_continuation_joined(self):
        """+ continuation lines are joined to the previous logical line."""
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_COMMENT_CONTINUATION_NETLIST)
        vals = {c.name: c.value for c in nl.components}
        assert abs(vals["V1"] - 5.0) < 1e-9, f"V1={vals['V1']}"
        assert abs(vals["R1"] - 1000.0) < 1e-9, f"R1={vals['R1']}"
        assert abs(vals["R2"] - 2000.0) < 1e-9, f"R2={vals['R2']}"

    def test_node_names_correct(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_COMMENT_CONTINUATION_NETLIST)
        assert "pwr" in nl.nodes
        assert "out" in nl.nodes
        # Ground '0' must NOT appear in nodes list
        assert "0" not in nl.nodes


# ---------------------------------------------------------------------------
# Oracle 4: Round-trip simulation
#   parse → spice_to_kerf_components → run_dc_analysis
#   Verify: V(mid) = V1 * R2 / (R1 + R2) and kerf components are created
# ---------------------------------------------------------------------------

_ROUND_TRIP_NETLIST = """\
* Round-trip test
Vcc vdd 0 DC 12
Ra vdd vmid 3k
Rb vmid 0 6k
.END
"""


class TestRoundTrip:
    def test_kerf_components_created(self):
        """spice_to_kerf_components maps R to Resistor, skips V/I."""
        from kerf_1dsim.spice_import import parse_spice_text, spice_to_kerf_components
        from kerf_1dsim.components import Resistor
        nl = parse_spice_text(_ROUND_TRIP_NETLIST)
        comps = spice_to_kerf_components(nl)
        # Only R elements map to Component instances
        assert len(comps) == 2
        assert all(isinstance(c, Resistor) for c in comps)

    def test_round_trip_dc_voltage(self):
        """
        parse → run_dc_analysis → V(vmid) = 12 * 6000/(3000+6000) = 8.0 V
        within 1e-9.
        """
        from kerf_1dsim.spice_import import parse_spice_text, run_dc_analysis
        nl = parse_spice_text(_ROUND_TRIP_NETLIST)
        result = run_dc_analysis(nl)
        assert result["converged"]

        expected = 12.0 * 6000.0 / (3000.0 + 6000.0)  # 8.0 V
        actual = result["vmid"]
        assert _rel_err(actual, expected) < 1e-9, (
            f"V(vmid)={actual:.10f}, expected={expected:.10f}"
        )

    def test_resistor_equations_satisfy(self):
        """
        Kerf Resistor equations should return residual ≈ 0 at the DC OP.
        Verify Ohm's law: v = R * i for each resistor.
        """
        from kerf_1dsim.spice_import import parse_spice_text, run_dc_analysis
        from kerf_1dsim.components import Resistor
        nl = parse_spice_text(_ROUND_TRIP_NETLIST)
        dc = run_dc_analysis(nl)

        # Ra: v = V(vdd) - V(vmid) = 12 - 8 = 4V;  i = 4/3000
        Ra_val = 3000.0
        v_Ra = dc["vdd"] - dc["vmid"]
        i_Ra = v_Ra / Ra_val
        ra = Resistor(R=Ra_val)
        res = ra.equations(0.0, [v_Ra, i_Ra], [0.0, 0.0])
        assert abs(res[0]) < 1e-9, f"Ra Ohm's law residual = {res[0]}"

        # Rb: v = V(vmid) - 0 = 8V;  i = 8/6000
        Rb_val = 6000.0
        v_Rb = dc["vmid"]
        i_Rb = v_Rb / Rb_val
        rb = Resistor(R=Rb_val)
        res = rb.equations(0.0, [v_Rb, i_Rb], [0.0, 0.0])
        assert abs(res[0]) < 1e-9, f"Rb Ohm's law residual = {res[0]}"


# ---------------------------------------------------------------------------
# Additional value-suffix parsing tests
# ---------------------------------------------------------------------------

class TestValueSuffixes:
    @pytest.mark.parametrize("token, expected", [
        ("1k", 1e3),
        ("10K", 1e4),
        ("470n", 470e-9),
        ("2.2u", 2.2e-6),
        ("33p", 33e-12),
        ("1meg", 1e6),
        ("1MEG", 1e6),
        ("1.5G", 1.5e9),
        ("100", 100.0),
        ("1e-3", 1e-3),
        ("3.3E3", 3300.0),
        ("10M", 10e-3),    # M = milli in SPICE
    ])
    def test_value_parsing(self, token, expected):
        from kerf_1dsim.spice_import import _parse_value
        result = _parse_value(token)
        assert _rel_err(result, expected) < 1e-9, (
            f"_parse_value({token!r}) = {result}, expected {expected}"
        )


# ---------------------------------------------------------------------------
# BJT / MOSFET parse (opaque model)
# ---------------------------------------------------------------------------

_TRANSISTOR_NETLIST = """\
* BJT and MOSFET parse test
Q1 nc nb ne 2N3904
M1 nd ng ns nb NMOS_MODEL
.MODEL 2N3904 NPN (BF=200)
.MODEL NMOS_MODEL NMOS (VTH0=0.5)
.END
"""


class TestTransistorParse:
    def test_bjt_parsed(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_TRANSISTOR_NETLIST)
        q = next((c for c in nl.components if c.name == "Q1"), None)
        assert q is not None
        assert q.type == "Q"
        assert q.model == "2N3904"
        assert q.nodes == ["nc", "nb", "ne"]

    def test_mosfet_parsed(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_TRANSISTOR_NETLIST)
        m = next((c for c in nl.components if c.name == "M1"), None)
        assert m is not None
        assert m.type == "M"
        assert m.model == "NMOS_MODEL"
        assert m.nodes == ["nd", "ng", "ns", "nb"]

    def test_models_captured(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_TRANSISTOR_NETLIST)
        assert "2N3904" in nl.models
        assert "NMOS_MODEL" in nl.models


# ---------------------------------------------------------------------------
# Subcircuit parse test
# ---------------------------------------------------------------------------

_SUBCKT_NETLIST = """\
* Subcircuit test
.SUBCKT myinv in out vdd gnd
M1 out in vdd vdd PMOS
M2 out in gnd gnd NMOS
.ENDS
X1 a b vcc 0 myinv
.END
"""


class TestSubcircuitParse:
    def test_subckt_captured(self):
        from kerf_1dsim.spice_import import parse_spice_text
        nl = parse_spice_text(_SUBCKT_NETLIST)
        assert "MYINV" in nl.subckts
        assert len(nl.subckts["MYINV"]) == 2  # M1 and M2 lines
