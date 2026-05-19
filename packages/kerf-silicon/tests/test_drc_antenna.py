"""
Tests for kerf_silicon.drc.antenna — process-step antenna DRC extension.

Covers the three required scenarios:

1. 100 µm² met1 metal + 0.1 µm² gate → ratio 1000 > 400 limit → violation
2. Same net but with a diode tap on met1 → ratio would be 1000 but discharged → no violation
3. Multi-step: violation at met1 resolves at met2
   (met1 step has ratio > met1 limit; adding met2 diode tap means the net is
   clean by the time met2 is processed)

All polygon coordinates are in µm so that areas are in µm².
"""

from __future__ import annotations

import pytest

from kerf_silicon.drc.antenna import (
    AntennaReport,
    AntennaViolation,
    SKY130_ANTENNA_LIMITS,
    check_antenna,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rect(layer: str, net: str, x0: float, y0: float, x1: float, y1: float,
         is_gate: bool = False, is_diode: bool = False) -> dict:
    """Return a rectangular shape dict with net annotation."""
    return {
        "layer": layer,
        "net": net,
        "polygon": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        "is_gate": is_gate,
        "is_diode": is_diode,
    }


# ---------------------------------------------------------------------------
# 1. Basic violation: 100 µm² met1 + 0.1 µm² gate → ratio 1000 > 400
# ---------------------------------------------------------------------------

class TestBasicAntennaViolation:
    """
    Gate area = 0.1 µm² (0.1 × 1.0 µm rectangle).
    Met1 area = 100 µm² (10 × 10 µm rectangle).
    Antenna ratio = 100 / 0.1 = 1000, SKY130 met1 limit = 400 → violation.
    """

    def _layout(self) -> list[dict]:
        return [
            rect("poly",  "net_a", 0.0, 0.0, 0.1, 1.0, is_gate=True),   # area = 0.1 µm²
            rect("met1",  "net_a", 0.0, 0.0, 10.0, 10.0),                # area = 100 µm²
        ]

    def test_violation_is_reported(self):
        report = check_antenna(self._layout())
        assert report.has_violations, "Expected an antenna violation but none were found"

    def test_exactly_one_violation(self):
        report = check_antenna(self._layout())
        assert len(report.violations) == 1

    def test_violation_net_and_layer(self):
        report = check_antenna(self._layout())
        v = report.violations[0]
        assert v.net == "net_a"
        assert v.layer == "met1"

    def test_violation_ratio_matches(self):
        report = check_antenna(self._layout())
        v = report.violations[0]
        assert abs(v.ratio - 1000.0) < 1e-6, f"Expected ratio 1000, got {v.ratio}"
        assert v.limit == 400.0

    def test_violation_description_contains_ratio(self):
        report = check_antenna(self._layout())
        v = report.violations[0]
        assert "1000" in v.description or "ratio" in v.description.lower()

    def test_checked_nets_count(self):
        report = check_antenna(self._layout())
        assert report.checked_nets >= 1

    def test_to_dict_structure(self):
        report = check_antenna(self._layout())
        d = report.to_dict()
        assert "violations" in d
        assert "checked_nets" in d
        assert "violation_count" in d
        assert d["violation_count"] == 1
        assert d["violations"][0]["net"] == "net_a"
        assert d["violations"][0]["layer"] == "met1"


# ---------------------------------------------------------------------------
# 2. Diode tap discharges the net — no violation
# ---------------------------------------------------------------------------

class TestDiodeTapDischargesNet:
    """
    Same geometry as TestBasicAntennaViolation but with a diode shape on met1.
    A diode tap on met1 means the net is discharged at that process step →
    ratio check is skipped → no violation.
    """

    def _layout_with_diode(self) -> list[dict]:
        return [
            rect("poly",  "net_b", 0.0, 0.0, 0.1, 1.0, is_gate=True),   # area = 0.1 µm²
            rect("met1",  "net_b", 0.0, 0.0, 10.0, 10.0),                # area = 100 µm²
            rect("diff",  "net_b", 0.5, 0.5, 1.5, 1.5, is_diode=True),   # diode on diff
        ]

    def test_no_violation_when_diode_on_met1_or_lower(self):
        # Diode is on "diff" which is below met1 in the process stack.
        # For the antenna check the diode layer is "diff"; if the process_steps
        # list only contains metal layers the diode resolves once met1 is present.
        # We provide a diode whose layer resolves before met1 in custom steps.
        layout = [
            rect("poly",  "net_b", 0.0, 0.0, 0.1, 1.0, is_gate=True),
            rect("met1",  "net_b", 0.0, 0.0, 10.0, 10.0),
            # Diode is present at met1 level (same layer = discharged at step 0)
            rect("met1",  "net_b", 5.0, 5.0, 5.5, 5.5, is_diode=True),
        ]
        report = check_antenna(layout, process_steps=["met1", "met2", "met3"])
        assert not report.has_violations, (
            f"Expected no violations with met1 diode tap; got: {report.violations}"
        )

    def test_diode_on_met1_clears_met1_violation(self):
        # Explicit: met1 diode present → met1 antenna ratio is not checked.
        layout = [
            rect("poly", "net_c", 0.0, 0.0, 0.1, 1.0, is_gate=True),
            rect("met1", "net_c", 0.0, 0.0, 20.0, 20.0),  # huge area, ratio = 4000
            rect("met1", "net_c", 21.0, 0.0, 21.5, 0.5, is_diode=True),
        ]
        report = check_antenna(layout, process_steps=["met1", "met2", "met3"])
        assert len(report.violations) == 0, (
            f"Diode tap should suppress violation; got: {report.violations}"
        )


# ---------------------------------------------------------------------------
# 3. Multi-step: violation at met1, resolves by met2 (diode added at met2)
# ---------------------------------------------------------------------------

class TestMultiStepViolationResolves:
    """
    At the met1 process step the cumulative metal area exceeds the met1 limit.
    A diode tap is added at the met2 layer, so at met2 and beyond the net is
    discharged.  Expected outcome:
      - 1 violation reported at met1
      - 0 additional violations at met2 or met3
    """

    def _layout(self) -> list[dict]:
        return [
            # Gate: 0.1 µm² area
            rect("poly",  "net_d", 0.0, 0.0, 0.1, 1.0, is_gate=True),
            # Met1: 100 µm² → ratio at met1 = 1000 > 400 → violation
            rect("met1",  "net_d", 0.0, 0.0, 10.0, 10.0),
            # Met2: additional 200 µm² → cumulative = 300 µm²
            # but diode is also on met2 → net discharged at met2 step → no met2 violation
            rect("met2",  "net_d", 0.0, 11.0, 20.0, 21.0),               # area = 200 µm²
            rect("met2",  "net_d", 21.0, 11.0, 21.5, 11.5, is_diode=True),
        ]

    def test_violation_at_met1(self):
        report = check_antenna(self._layout(), process_steps=["met1", "met2", "met3"])
        met1_violations = [v for v in report.violations if v.layer == "met1"]
        assert len(met1_violations) == 1, (
            f"Expected exactly 1 met1 violation; got: {met1_violations}"
        )

    def test_no_violation_at_met2(self):
        report = check_antenna(self._layout(), process_steps=["met1", "met2", "met3"])
        met2_violations = [v for v in report.violations if v.layer == "met2"]
        assert len(met2_violations) == 0, (
            f"Expected no met2 violations (diode discharges net); got: {met2_violations}"
        )

    def test_total_violation_count_is_one(self):
        report = check_antenna(self._layout(), process_steps=["met1", "met2", "met3"])
        assert len(report.violations) == 1, (
            f"Expected exactly 1 total violation; got {len(report.violations)}: "
            f"{report.violations}"
        )

    def test_met1_violation_ratio(self):
        report = check_antenna(self._layout(), process_steps=["met1", "met2", "met3"])
        v = report.violations[0]
        assert v.layer == "met1"
        # met1 area = 100, gate = 0.1 → ratio = 1000
        assert abs(v.ratio - 1000.0) < 1e-6


# ---------------------------------------------------------------------------
# 4. Custom antenna limits
# ---------------------------------------------------------------------------

class TestCustomLimits:
    def test_custom_limit_not_exceeded(self):
        """
        Same 100/0.1 = 1000× geometry but limit set to 2000 → no violation.
        """
        layout = [
            rect("poly",  "net_e", 0.0, 0.0, 0.1, 1.0, is_gate=True),
            rect("met1",  "net_e", 0.0, 0.0, 10.0, 10.0),
        ]
        report = check_antenna(layout, rules={"met1": 2000.0})
        assert not report.has_violations

    def test_custom_limit_exceeded(self):
        """
        Same geometry, limit set to 500 < 1000 → violation.
        """
        layout = [
            rect("poly",  "net_f", 0.0, 0.0, 0.1, 1.0, is_gate=True),
            rect("met1",  "net_f", 0.0, 0.0, 10.0, 10.0),
        ]
        report = check_antenna(layout, rules={"met1": 500.0})
        assert report.has_violations
        assert report.violations[0].limit == 500.0


# ---------------------------------------------------------------------------
# 5. Net without gate shapes is not checked
# ---------------------------------------------------------------------------

class TestNetWithoutGate:
    def test_net_with_no_gate_produces_no_violation(self):
        """
        A net with large metal area but no gate shape is not antenna-relevant
        (no gate oxide to damage) and must not produce a false violation.
        """
        layout = [
            rect("met1", "net_g", 0.0, 0.0, 100.0, 100.0),  # no is_gate
        ]
        report = check_antenna(layout)
        assert not report.has_violations

    def test_checked_nets_excludes_gateless_nets(self):
        layout = [
            rect("met1", "net_g", 0.0, 0.0, 100.0, 100.0),
        ]
        report = check_antenna(layout)
        assert report.checked_nets == 0


# ---------------------------------------------------------------------------
# 6. Empty layout
# ---------------------------------------------------------------------------

class TestEmptyLayout:
    def test_empty_layout_returns_no_violations(self):
        report = check_antenna([])
        assert not report.has_violations
        assert report.checked_nets == 0


# ---------------------------------------------------------------------------
# 7. SKY130 default limits sanity check
# ---------------------------------------------------------------------------

class TestSKY130DefaultLimits:
    def test_default_limits_present(self):
        assert "met1" in SKY130_ANTENNA_LIMITS
        assert "met2" in SKY130_ANTENNA_LIMITS
        assert "met3" in SKY130_ANTENNA_LIMITS

    def test_default_limits_values(self):
        assert SKY130_ANTENNA_LIMITS["met1"] == 400.0
        assert SKY130_ANTENNA_LIMITS["met2"] == 600.0
        assert SKY130_ANTENNA_LIMITS["met3"] == 800.0

    def test_default_limits_used_when_none_passed(self):
        """Omitting rules= should fall back to SKY130 defaults."""
        layout = [
            rect("poly", "net_h", 0.0, 0.0, 0.1, 1.0, is_gate=True),
            rect("met1", "net_h", 0.0, 0.0, 10.0, 10.0),  # ratio 1000 > 400 default
        ]
        report = check_antenna(layout)
        assert report.has_violations
        assert report.violations[0].limit == 400.0
