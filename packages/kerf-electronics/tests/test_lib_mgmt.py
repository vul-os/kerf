"""
Tests for kerf_electronics.tools.lib_mgmt — footprint/symbol library
management and assignment validation.

DoD requirements explicitly tested:
  - pin/pad mismatch is flagged
  - missing footprint is flagged

All tests are hermetic (no network, no filesystem, no DB).
"""

import json
import unittest

# Import the tools module so @register decorators fire and tools land in Registry.
import kerf_electronics.tools.lib_mgmt  # noqa: F401

from kerf_electronics.tools.lib_mgmt import (
    assign_footprint,
    check_library_assignments,
    _refdes_ok,
    _pin_count,
    _pad_count,
    _footprint_ref,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _sym(pin_count: int, library: str = "Device", entry_name: str = "R") -> dict:
    """Minimal schematic_symbol dict matching kicad_library shape."""
    return {
        "library": library,
        "entry_name": entry_name,
        "description": "",
        "datasheet_url": "",
        "pin_count": pin_count,
        "pins": [{"name": f"P{i}", "number": str(i), "electrical_type": "passive"}
                 for i in range(1, pin_count + 1)],
    }


def _fp(pad_count: int, library: str = "Resistor_SMD", entry_name: str = "R_0402") -> dict:
    """Minimal pcb_footprint dict matching kicad_library shape."""
    return {
        "library": library,
        "entry_name": entry_name,
        "description": "",
        "tags": "",
        "layer": "F.Cu",
        "pad_count": pad_count,
        "pads": [{"number": str(i), "type": "smd", "shape": "rect",
                  "position": {"x": 0.0, "y": 0.0}, "size": {"x": 1.0, "y": 0.5},
                  "layers": ["F.Cu"]}
                 for i in range(1, pad_count + 1)],
    }


def _comp(refdes: str, pin_count: int = 2, pad_count: int | None = 2) -> dict:
    """Component dict with valid symbol and matching-or-mismatched footprint."""
    c: dict = {
        "refdes": refdes,
        "name": f"{refdes}_value",
        "category": "electronic",
        "schematic_symbol": _sym(pin_count),
        "pcb_footprint": _fp(pad_count) if pad_count is not None else None,
        "model_3d_paths": [],
        "content_hash": "abc123",
    }
    return c


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_refdes_ok_valid(self):
        self.assertTrue(_refdes_ok("R1"))
        self.assertTrue(_refdes_ok("U12"))
        self.assertTrue(_refdes_ok("C100"))
        self.assertTrue(_refdes_ok("LED1"))

    def test_refdes_ok_invalid(self):
        self.assertFalse(_refdes_ok(""))
        self.assertFalse(_refdes_ok("1R"))    # digits first
        self.assertFalse(_refdes_ok("R"))     # no trailing digit
        self.assertFalse(_refdes_ok("R 1"))   # space

    def test_pin_count_from_field(self):
        sym = {"pin_count": 8, "pins": []}
        self.assertEqual(_pin_count(sym), 8)

    def test_pin_count_fallback_to_pins_list(self):
        sym = {"pins": [1, 2, 3]}
        self.assertEqual(_pin_count(sym), 3)

    def test_pin_count_none(self):
        self.assertIsNone(_pin_count(None))

    def test_pad_count_from_field(self):
        fp = {"pad_count": 4, "pads": []}
        self.assertEqual(_pad_count(fp), 4)

    def test_pad_count_fallback_to_pads_list(self):
        fp = {"pads": [1, 2]}
        self.assertEqual(_pad_count(fp), 2)

    def test_pad_count_none(self):
        self.assertIsNone(_pad_count(None))

    def test_footprint_ref_full(self):
        fp = {"library": "Resistor_SMD", "entry_name": "R_0402"}
        self.assertEqual(_footprint_ref(fp), "Resistor_SMD:R_0402")

    def test_footprint_ref_entry_only(self):
        fp = {"library": "", "entry_name": "R_0402"}
        self.assertEqual(_footprint_ref(fp), "R_0402")


# ---------------------------------------------------------------------------
# assign_footprint — pure-function tests
# ---------------------------------------------------------------------------

class TestAssignFootprint(unittest.TestCase):

    def _components(self):
        return [
            {"refdes": "R1", "name": "10k", "schematic_symbol": _sym(2), "pcb_footprint": None},
            {"refdes": "U1", "name": "MCU", "schematic_symbol": _sym(8), "pcb_footprint": None},
            {"refdes": "C1", "name": "100nF", "schematic_symbol": _sym(2), "pcb_footprint": None},
        ]

    def test_explicit_assignment_applied(self):
        comps = self._components()
        result = assign_footprint(
            comps,
            assignments={"R1": "Resistor_SMD:R_0402"},
            lib_table={},
        )
        self.assertIn("R1", result["updated"])
        r1 = next(c for c in result["components"] if c["refdes"] == "R1")
        self.assertIsNotNone(r1["pcb_footprint"])
        self.assertEqual(r1["pcb_footprint"]["library"], "Resistor_SMD")
        self.assertEqual(r1["pcb_footprint"]["entry_name"], "R_0402")
        self.assertEqual(r1["footprint_ref"], "Resistor_SMD:R_0402")

    def test_multiple_assignments(self):
        comps = self._components()
        result = assign_footprint(
            comps,
            assignments={
                "R1": "Resistor_SMD:R_0402",
                "U1": "Package_DIP:DIP-8_W7.62mm",
            },
            lib_table={},
        )
        self.assertEqual(sorted(result["updated"]), ["R1", "U1"])
        self.assertEqual(result["not_found"], [])

    def test_not_found_refdes_reported(self):
        comps = self._components()
        result = assign_footprint(
            comps,
            assignments={"X99": "Lib:FP"},
            lib_table={},
        )
        self.assertIn("X99", result["not_found"])
        self.assertEqual(result["updated"], [])

    def test_unassigned_components_unchanged(self):
        comps = self._components()
        result = assign_footprint(
            comps,
            assignments={"R1": "Resistor_SMD:R_0402"},
            lib_table={},
        )
        u1 = next(c for c in result["components"] if c["refdes"] == "U1")
        self.assertIsNone(u1["pcb_footprint"])

    def test_auto_suggest_returns_suggestion(self):
        comps = self._components()
        result = assign_footprint(
            comps,
            assignments={},
            lib_table={"Resistor_SMD": "/usr/share/kicad/footprints/Resistor_SMD.pretty"},
            auto_suggest=True,
        )
        # At least one component should get a suggestion since lib_table is non-empty
        self.assertIsInstance(result["suggested"], dict)
        self.assertGreater(len(result["suggested"]), 0)

    def test_auto_suggest_false_no_suggestions(self):
        comps = self._components()
        result = assign_footprint(
            comps,
            assignments={},
            lib_table={"Resistor_SMD": "/path"},
            auto_suggest=False,
        )
        self.assertEqual(result["suggested"], {})

    def test_lib_table_passthrough(self):
        lib = {"Resistor_SMD": "/path/to/Resistor_SMD.pretty"}
        result = assign_footprint([], {}, lib)
        self.assertEqual(result["lib_table"], lib)

    def test_bare_entry_assignment(self):
        """Assignment without 'Lib:' prefix should store empty library."""
        comps = [{"refdes": "R1", "schematic_symbol": None, "pcb_footprint": None}]
        result = assign_footprint(comps, {"R1": "R_0402"}, {})
        r1 = result["components"][0]
        self.assertEqual(r1["pcb_footprint"]["library"], "")
        self.assertEqual(r1["pcb_footprint"]["entry_name"], "R_0402")


# ---------------------------------------------------------------------------
# check_library_assignments — DoD requirement: pin/pad mismatch flagged
# ---------------------------------------------------------------------------

class TestCheckAssignments_PinPadMismatch(unittest.TestCase):
    """Ensure a pin/pad count mismatch is flagged as an error."""

    def test_mismatch_flagged(self):
        """Symbol has 2 pins; footprint has 4 pads → pin_pad_mismatch error."""
        comps = [_comp("R1", pin_count=2, pad_count=4)]
        report = check_library_assignments(comps)

        self.assertEqual(report["status"], "ISSUES_FOUND")
        kinds = [i["kind"] for i in report["issues"]]
        self.assertIn("pin_pad_mismatch", kinds)

    def test_mismatch_message_contains_counts(self):
        comps = [_comp("R1", pin_count=2, pad_count=4)]
        report = check_library_assignments(comps)
        mm = next(i for i in report["issues"] if i["kind"] == "pin_pad_mismatch")
        self.assertIn("2", mm["message"])
        self.assertIn("4", mm["message"])

    def test_mismatch_refdes_in_issue(self):
        comps = [_comp("U3", pin_count=8, pad_count=14)]
        report = check_library_assignments(comps)
        mm = next(i for i in report["issues"] if i["kind"] == "pin_pad_mismatch")
        self.assertEqual(mm["refdes"], "U3")

    def test_mismatch_severity_is_error(self):
        comps = [_comp("R1", pin_count=2, pad_count=4)]
        report = check_library_assignments(comps)
        mm = next(i for i in report["issues"] if i["kind"] == "pin_pad_mismatch")
        self.assertEqual(mm["severity"], "error")

    def test_no_mismatch_when_counts_match(self):
        comps = [_comp("R1", pin_count=2, pad_count=2)]
        report = check_library_assignments(comps)
        kinds = [i["kind"] for i in report["issues"]]
        self.assertNotIn("pin_pad_mismatch", kinds)

    def test_summary_counts_mismatch(self):
        comps = [
            _comp("R1", pin_count=2, pad_count=4),
            _comp("C1", pin_count=2, pad_count=2),
        ]
        report = check_library_assignments(comps)
        self.assertEqual(report["summary"]["pin_pad_mismatch"], 1)

    def test_multiple_mismatches(self):
        comps = [
            _comp("R1", pin_count=2, pad_count=4),
            _comp("U1", pin_count=8, pad_count=14),
        ]
        report = check_library_assignments(comps)
        mismatches = [i for i in report["issues"] if i["kind"] == "pin_pad_mismatch"]
        self.assertEqual(len(mismatches), 2)
        self.assertEqual(report["summary"]["pin_pad_mismatch"], 2)

    def test_no_mismatch_when_fp_has_no_pad_count(self):
        """Footprint with pad_count=None (lightweight assignment) skips check."""
        comp = {
            "refdes": "R1",
            "schematic_symbol": _sym(2),
            "pcb_footprint": {"library": "Lib", "entry_name": "FP"},  # no pad_count
        }
        report = check_library_assignments([comp])
        kinds = [i["kind"] for i in report["issues"]]
        self.assertNotIn("pin_pad_mismatch", kinds)


# ---------------------------------------------------------------------------
# check_library_assignments — DoD requirement: missing footprint flagged
# ---------------------------------------------------------------------------

class TestCheckAssignments_MissingFootprint(unittest.TestCase):
    """Ensure a missing footprint is flagged as an error."""

    def test_missing_footprint_flagged(self):
        """Component with pcb_footprint=None and no footprint_ref → missing_footprint."""
        comps = [_comp("R1", pad_count=None)]  # pad_count=None → pcb_footprint=None
        report = check_library_assignments(comps)

        self.assertEqual(report["status"], "ISSUES_FOUND")
        kinds = [i["kind"] for i in report["issues"]]
        self.assertIn("missing_footprint", kinds)

    def test_missing_footprint_refdes_in_issue(self):
        comps = [_comp("C3", pad_count=None)]
        report = check_library_assignments(comps)
        mf = next(i for i in report["issues"] if i["kind"] == "missing_footprint")
        self.assertEqual(mf["refdes"], "C3")

    def test_missing_footprint_severity_is_error(self):
        comps = [_comp("R1", pad_count=None)]
        report = check_library_assignments(comps)
        mf = next(i for i in report["issues"] if i["kind"] == "missing_footprint")
        self.assertEqual(mf["severity"], "error")

    def test_footprint_ref_string_accepted(self):
        """A component with a footprint_ref string should NOT trigger missing_footprint."""
        comp = {
            "refdes": "R1",
            "schematic_symbol": _sym(2),
            "pcb_footprint": None,
            "footprint_ref": "Resistor_SMD:R_0402",
        }
        report = check_library_assignments([comp])
        kinds = [i["kind"] for i in report["issues"]]
        self.assertNotIn("missing_footprint", kinds)

    def test_summary_counts_missing_footprint(self):
        comps = [
            _comp("R1", pad_count=None),
            _comp("C1", pad_count=2),   # has footprint
            _comp("U1", pad_count=None),
        ]
        report = check_library_assignments(comps)
        self.assertEqual(report["summary"]["missing_footprint"], 2)

    def test_all_good_returns_ok(self):
        comps = [
            _comp("R1", pin_count=2, pad_count=2),
            _comp("C1", pin_count=2, pad_count=2),
        ]
        report = check_library_assignments(comps)
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["issues"], [])

    def test_empty_components_ok(self):
        report = check_library_assignments([])
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["total"], 0)


# ---------------------------------------------------------------------------
# check_library_assignments — refdes checks
# ---------------------------------------------------------------------------

class TestCheckAssignments_Refdes(unittest.TestCase):

    def test_missing_refdes_flagged(self):
        comp = {"refdes": "", "schematic_symbol": _sym(2), "pcb_footprint": _fp(2)}
        report = check_library_assignments([comp])
        kinds = [i["kind"] for i in report["issues"]]
        self.assertIn("missing_refdes", kinds)

    def test_none_refdes_flagged(self):
        comp = {"schematic_symbol": _sym(2), "pcb_footprint": _fp(2)}
        report = check_library_assignments([comp])
        kinds = [i["kind"] for i in report["issues"]]
        self.assertIn("missing_refdes", kinds)

    def test_duplicate_refdes_flagged(self):
        comps = [_comp("R1"), _comp("R1")]
        report = check_library_assignments(comps)
        kinds = [i["kind"] for i in report["issues"]]
        self.assertIn("duplicate_refdes", kinds)

    def test_duplicate_refdes_message_mentions_both_indices(self):
        comps = [_comp("R1"), _comp("R1")]
        report = check_library_assignments(comps)
        dup = next(i for i in report["issues"] if i["kind"] == "duplicate_refdes")
        self.assertIn("0", dup["message"])
        self.assertIn("1", dup["message"])

    def test_invalid_refdes_format_is_warning(self):
        comp = {"refdes": "BAD-REF", "schematic_symbol": _sym(2), "pcb_footprint": _fp(2)}
        report = check_library_assignments([comp])
        bad = [i for i in report["issues"] if i["kind"] == "invalid_refdes_format"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["severity"], "warning")

    def test_valid_refdes_no_format_warning(self):
        for ref in ("R1", "U3", "LED10", "C100"):
            comp = {"refdes": ref, "schematic_symbol": _sym(2), "pcb_footprint": _fp(2)}
            report = check_library_assignments([comp])
            bad = [i for i in report["issues"] if i["kind"] == "invalid_refdes_format"]
            self.assertEqual(bad, [], f"Unexpected format warning for '{ref}'")


# ---------------------------------------------------------------------------
# check_library_assignments — combined scenario
# ---------------------------------------------------------------------------

class TestCheckAssignments_Combined(unittest.TestCase):
    """A realistic design with several simultaneous issues."""

    def setUp(self):
        self.components = [
            _comp("R1", pin_count=2, pad_count=2),   # OK
            _comp("R2", pin_count=2, pad_count=4),   # pin/pad mismatch
            _comp("U1", pin_count=8, pad_count=8),   # OK
            _comp("",   pin_count=2, pad_count=2),   # missing refdes (empty string)
            _comp("C1", pad_count=None),              # missing footprint
            _comp("R1", pin_count=2, pad_count=2),   # duplicate refdes
        ]
        self.report = check_library_assignments(self.components)

    def test_status_issues_found(self):
        self.assertEqual(self.report["status"], "ISSUES_FOUND")

    def test_total_count(self):
        self.assertEqual(self.report["total"], 6)

    def test_missing_footprint_count(self):
        self.assertEqual(self.report["summary"]["missing_footprint"], 1)

    def test_pin_pad_mismatch_count(self):
        self.assertEqual(self.report["summary"]["pin_pad_mismatch"], 1)

    def test_duplicate_refdes_count(self):
        self.assertEqual(self.report["summary"]["duplicate_refdes"], 1)

    def test_missing_refdes_count(self):
        self.assertEqual(self.report["summary"]["missing_refdes"], 1)

    def test_r1_mismatch_not_double_counted(self):
        """The duplicate R1 should not create a second pin_pad_mismatch — only R2 mismatches."""
        mismatches = [i for i in self.report["issues"] if i["kind"] == "pin_pad_mismatch"]
        refdes_list = [i["refdes"] for i in mismatches]
        self.assertIn("R2", refdes_list)
        self.assertNotIn("R1", refdes_list)

    def test_lib_table_included_in_report(self):
        lib = {"Device": "/path/Device.kicad_sym"}
        report = check_library_assignments(self.components, lib_table=lib)
        self.assertEqual(report["lib_table"], lib)


# ---------------------------------------------------------------------------
# LLM tool integration tests (async, via Registry)
# ---------------------------------------------------------------------------

class TestLibMgmtTools(unittest.IsolatedAsyncioTestCase):

    async def test_assign_footprint_tool_registered(self):
        from kerf_chat.tools.registry import Registry
        names = {t.spec.name for t in Registry}
        self.assertIn("assign_footprint", names)

    async def test_check_library_assignments_tool_registered(self):
        from kerf_chat.tools.registry import Registry
        names = {t.spec.name for t in Registry}
        self.assertIn("check_library_assignments", names)

    async def test_assign_footprint_tool_runs(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "assign_footprint")
        components = [
            {"refdes": "R1", "schematic_symbol": _sym(2), "pcb_footprint": None},
        ]
        payload = json.dumps({
            "components": components,
            "assignments": {"R1": "Resistor_SMD:R_0402"},
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertIn("R1", result["updated"])
        self.assertIn("components", result)
        self.assertIn("message", result)

    async def test_check_library_assignments_tool_ok(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "check_library_assignments")
        components = [_comp("R1", 2, 2), _comp("C1", 2, 2)]
        payload = json.dumps({"components": components}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertEqual(result["status"], "OK")
        self.assertIn("message", result)

    async def test_check_tool_flags_missing_footprint(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "check_library_assignments")
        components = [_comp("R1", 2, None)]  # no footprint
        payload = json.dumps({"components": components}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertEqual(result["status"], "ISSUES_FOUND")
        kinds = [i["kind"] for i in result["issues"]]
        self.assertIn("missing_footprint", kinds)

    async def test_check_tool_flags_pin_pad_mismatch(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "check_library_assignments")
        components = [_comp("R1", pin_count=2, pad_count=4)]
        payload = json.dumps({"components": components}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertEqual(result["status"], "ISSUES_FOUND")
        kinds = [i["kind"] for i in result["issues"]]
        self.assertIn("pin_pad_mismatch", kinds)

    async def test_assign_bad_args(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "assign_footprint")
        payload = json.dumps({"components": "not-a-list", "assignments": {}}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertIn("error", result)

    async def test_check_bad_args(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "check_library_assignments")
        payload = json.dumps({"components": "not-a-list"}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
