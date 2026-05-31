"""
Tests for kerf_mold.gate_vestige_check
=======================================
Covers vestige estimation, cosmetic class assignment, compliance checks,
removal method lookup, and error handling.

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007, §7.6.
  Menges et al. How to Make Injection Molds, 3rd ed., Hanser 2001, §6.6.
"""

import pytest

from kerf_mold.gate_vestige_check import (
    COSMETIC_CLASS_LIMITS_MM,
    GateSpec,
    GateVestigeReport,
    check_gate_vestige,
    _class_achieved,
    _class_compliant,
    _estimate_vestige_mm,
)


# ---------------------------------------------------------------------------
# 1. Submarine gate → ~0.05 mm → A2 class achieved (within A2 bounds)
# ---------------------------------------------------------------------------

def test_submarine_gate_vestige_and_a2_compliance():
    gate = GateSpec(
        gate_type="submarine",
        gate_thickness_mm=0.8,
        gate_width_mm=2.0,
        polymer_grade="ABS",
    )
    report = check_gate_vestige(gate, required_class="A2")
    assert report.estimated_vestige_mm == pytest.approx(0.05, abs=1e-9)
    assert report.cosmetic_class_achieved == "A2"
    assert report.compliant is True
    assert report.cosmetic_class_required == "A2"


# ---------------------------------------------------------------------------
# 2. Edge gate 1mm thick → 1mm vestige → only B class compliant
# ---------------------------------------------------------------------------

def test_edge_gate_1mm_achieves_b_not_a3():
    gate = GateSpec(
        gate_type="edge",
        gate_thickness_mm=1.0,
        gate_width_mm=5.0,
        polymer_grade="PP",
    )
    report = check_gate_vestige(gate, required_class="B")
    assert report.estimated_vestige_mm == pytest.approx(1.0, abs=1e-9)
    assert report.cosmetic_class_achieved == "B"
    assert report.compliant is True


def test_edge_gate_1mm_not_compliant_with_a3():
    gate = GateSpec(
        gate_type="edge",
        gate_thickness_mm=1.0,
        gate_width_mm=5.0,
        polymer_grade="PP",
    )
    report = check_gate_vestige(gate, required_class="A3")
    assert report.compliant is False
    assert report.cosmetic_class_achieved == "B"
    assert report.cosmetic_class_required == "A3"


def test_edge_gate_1mm_not_compliant_with_a2():
    gate = GateSpec(
        gate_type="edge",
        gate_thickness_mm=1.0,
        gate_width_mm=5.0,
        polymer_grade="PC",
    )
    report = check_gate_vestige(gate, required_class="A2")
    assert report.compliant is False


# ---------------------------------------------------------------------------
# 3. Hot-tip gate → A2 for required A2
# ---------------------------------------------------------------------------

def test_hot_tip_gate_meets_a3_requirement():
    gate = GateSpec(
        gate_type="hot_tip",
        gate_thickness_mm=1.0,
        gate_width_mm=1.0,
        polymer_grade="PC",
    )
    # hot_tip vestige = 0.20 mm → class A3
    report = check_gate_vestige(gate, required_class="A3")
    assert report.estimated_vestige_mm == pytest.approx(0.20, abs=1e-9)
    assert report.cosmetic_class_achieved == "A3"
    assert report.compliant is True


def test_hot_tip_gate_not_a2_compliant():
    gate = GateSpec(
        gate_type="hot_tip",
        gate_thickness_mm=1.0,
        gate_width_mm=1.0,
        polymer_grade="ABS",
    )
    # 0.20 mm exceeds A2 limit of 0.10 mm
    report = check_gate_vestige(gate, required_class="A2")
    assert report.compliant is False
    assert report.cosmetic_class_achieved == "A3"


# ---------------------------------------------------------------------------
# 4. Pin-point → A2 compliant for low requirement
# ---------------------------------------------------------------------------

def test_pin_point_gate_a2_compliant():
    gate = GateSpec(
        gate_type="pin_point",
        gate_thickness_mm=0.5,
        gate_width_mm=0.5,
        polymer_grade="POM",
    )
    report = check_gate_vestige(gate, required_class="A2")
    assert report.estimated_vestige_mm == pytest.approx(0.10, abs=1e-9)
    assert report.cosmetic_class_achieved == "A2"
    assert report.compliant is True


def test_pin_point_gate_not_a1_compliant():
    gate = GateSpec(
        gate_type="pin_point",
        gate_thickness_mm=0.5,
        gate_width_mm=0.5,
        polymer_grade="ABS",
    )
    # 0.10 mm > A1 limit (0.0)
    report = check_gate_vestige(gate, required_class="A1")
    assert report.compliant is False


# ---------------------------------------------------------------------------
# 5. Unknown gate type → ValueError raised
# ---------------------------------------------------------------------------

def test_unknown_gate_type_raises():
    with pytest.raises(ValueError, match="Unknown gate_type"):
        GateSpec(
            gate_type="sprue_gate",
            gate_thickness_mm=1.0,
            gate_width_mm=2.0,
            polymer_grade="ABS",
        )


# ---------------------------------------------------------------------------
# 6. Tunnel gate vestige is in expected range
# ---------------------------------------------------------------------------

def test_tunnel_gate_vestige_central_value():
    gate = GateSpec(
        gate_type="tunnel",
        gate_thickness_mm=1.2,
        gate_width_mm=2.0,
        polymer_grade="PP",
    )
    report = check_gate_vestige(gate, required_class="A2")
    # Tunnel central estimate: 0.10 mm → exactly at A2 limit (≤ 0.10)
    assert report.estimated_vestige_mm == pytest.approx(0.10, abs=1e-9)
    assert report.cosmetic_class_achieved == "A2"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 7. Fan gate → same as edge gate (thickness-driven)
# ---------------------------------------------------------------------------

def test_fan_gate_vestige_equals_thickness():
    gate = GateSpec(
        gate_type="fan",
        gate_thickness_mm=0.8,
        gate_width_mm=20.0,
        polymer_grade="ABS",
    )
    report = check_gate_vestige(gate, required_class="A3")
    assert report.estimated_vestige_mm == pytest.approx(0.8, abs=1e-9)
    # 0.8 mm ≤ B limit (1.0) but > A3 limit (0.3)
    assert report.cosmetic_class_achieved == "B"
    assert report.compliant is False


# ---------------------------------------------------------------------------
# 8. Film gate → 0.50 mm vestige → B class
# ---------------------------------------------------------------------------

def test_film_gate_vestige_and_class():
    gate = GateSpec(
        gate_type="film",
        gate_thickness_mm=0.5,
        gate_width_mm=50.0,
        polymer_grade="PP",
    )
    report = check_gate_vestige(gate, required_class="B")
    assert report.estimated_vestige_mm == pytest.approx(0.50, abs=1e-9)
    assert report.cosmetic_class_achieved == "B"
    assert report.compliant is True


# ---------------------------------------------------------------------------
# 9. C class: any vestige is acceptable
# ---------------------------------------------------------------------------

def test_c_class_always_compliant():
    for gt in ("edge", "fan", "film"):
        gate = GateSpec(
            gate_type=gt,
            gate_thickness_mm=2.0,
            gate_width_mm=10.0,
            polymer_grade="PC",
        )
        report = check_gate_vestige(gate, required_class="C")
        assert report.compliant is True, f"{gt} gate should be C-compliant"


# ---------------------------------------------------------------------------
# 10. GateSpec validation: thickness ≤ 0 raises
# ---------------------------------------------------------------------------

def test_gate_spec_zero_thickness_raises():
    with pytest.raises(ValueError, match="gate_thickness_mm must be > 0"):
        GateSpec(
            gate_type="edge",
            gate_thickness_mm=0.0,
            gate_width_mm=5.0,
            polymer_grade="ABS",
        )


def test_gate_spec_negative_width_raises():
    with pytest.raises(ValueError, match="gate_width_mm must be > 0"):
        GateSpec(
            gate_type="edge",
            gate_thickness_mm=1.0,
            gate_width_mm=-1.0,
            polymer_grade="ABS",
        )


# ---------------------------------------------------------------------------
# 11. Required class validation
# ---------------------------------------------------------------------------

def test_invalid_required_class_raises():
    gate = GateSpec(
        gate_type="submarine",
        gate_thickness_mm=1.0,
        gate_width_mm=2.0,
        polymer_grade="ABS",
    )
    with pytest.raises(ValueError, match="Unknown required_class"):
        check_gate_vestige(gate, required_class="AA")


# ---------------------------------------------------------------------------
# 12. Removal method is populated for all known gate types
# ---------------------------------------------------------------------------

def test_removal_method_populated_all_gate_types():
    gate_types = ["edge", "tunnel", "submarine", "hot_tip", "pin_point", "fan", "film"]
    for gt in gate_types:
        gate = GateSpec(
            gate_type=gt,
            gate_thickness_mm=1.0,
            gate_width_mm=3.0,
            polymer_grade="ABS",
        )
        report = check_gate_vestige(gate, required_class="B")
        assert report.removal_method, f"removal_method should be non-empty for {gt}"


# ---------------------------------------------------------------------------
# 13. Honest caveat mentions Beaumont and melt temperature
# ---------------------------------------------------------------------------

def test_honest_caveat_content():
    gate = GateSpec(
        gate_type="edge",
        gate_thickness_mm=1.0,
        gate_width_mm=5.0,
        polymer_grade="PC",
    )
    report = check_gate_vestige(gate)
    assert "Beaumont" in report.honest_caveat
    assert "melt temperature" in report.honest_caveat
    assert "PC" in report.honest_caveat


# ---------------------------------------------------------------------------
# 14. Default required_class is A2
# ---------------------------------------------------------------------------

def test_default_required_class_is_a2():
    gate = GateSpec(
        gate_type="submarine",
        gate_thickness_mm=1.0,
        gate_width_mm=2.0,
        polymer_grade="ABS",
    )
    report = check_gate_vestige(gate)
    assert report.cosmetic_class_required == "A2"


# ---------------------------------------------------------------------------
# 15. Cosmetic class limits table sanity
# ---------------------------------------------------------------------------

def test_cosmetic_class_limits_values():
    assert COSMETIC_CLASS_LIMITS_MM["A1"] == 0.0
    assert COSMETIC_CLASS_LIMITS_MM["A2"] == pytest.approx(0.1)
    assert COSMETIC_CLASS_LIMITS_MM["A3"] == pytest.approx(0.3)
    assert COSMETIC_CLASS_LIMITS_MM["B"] == pytest.approx(1.0)
    assert COSMETIC_CLASS_LIMITS_MM["C"] is None


# ---------------------------------------------------------------------------
# 16. Class hierarchy: A1 stricter than A2 stricter than A3 etc.
# ---------------------------------------------------------------------------

def test_class_hierarchy_ordering():
    # A1 achieved is compliant with A1, A2, A3, B, C
    for req in ("A1", "A2", "A3", "B", "C"):
        assert _class_compliant("A1", req), f"A1 should comply with {req}"
    # B achieved is compliant with B and C only
    assert _class_compliant("B", "B")
    assert _class_compliant("B", "C")
    assert not _class_compliant("B", "A3")
    assert not _class_compliant("B", "A2")
    assert not _class_compliant("B", "A1")


# ---------------------------------------------------------------------------
# 17. Edge gate 0.09 mm → achieves A2 (thin edge gate within spec)
# ---------------------------------------------------------------------------

def test_edge_gate_thin_achieves_a2():
    gate = GateSpec(
        gate_type="edge",
        gate_thickness_mm=0.09,
        gate_width_mm=3.0,
        polymer_grade="ABS",
    )
    report = check_gate_vestige(gate, required_class="A2")
    assert report.estimated_vestige_mm == pytest.approx(0.09, abs=1e-9)
    assert report.compliant is True
    assert report.cosmetic_class_achieved == "A2"
