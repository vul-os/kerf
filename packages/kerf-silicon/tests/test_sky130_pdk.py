"""test_sky130_pdk.py — pytest suite for the SKY130 PDK integration.

Run with:
  PYTHONPATH=packages/kerf-core/src:packages/kerf-silicon/src \
    python3 -m pytest packages/kerf-silicon/tests/test_sky130_pdk.py -x
"""

from __future__ import annotations

import os
import sys
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap (mirrors the electronics conftest pattern so this file
# works whether collected by the repo-wide pytest run or invoked directly)
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SILICON_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SILICON_SRC not in sys.path:
    sys.path.insert(0, _SILICON_SRC)


from kerf_silicon.pdk.sky130.layers import LAYERS, get_layer
from kerf_silicon.pdk.sky130.std_cells import STD_CELLS, get_cell
from kerf_silicon.pdk.sky130.design_rules import DESIGN_RULES, get_rule
from kerf_silicon.pdk.sky130.installer import is_pdk_available, install_hint
from kerf_silicon.pdk.sky130 import SKY130_PDK


# ===========================================================================
# Layer tests
# ===========================================================================

class TestLayers(unittest.TestCase):
    def test_at_least_35_layers(self):
        self.assertGreaterEqual(len(LAYERS), 35)

    def test_each_layer_has_required_fields(self):
        required = {"name", "gds_layer", "gds_datatype", "color", "description"}
        for lyr in LAYERS:
            missing = required - set(lyr.keys())
            self.assertFalse(missing, f"Layer {lyr.get('name')} missing fields: {missing}")

    def test_known_layers_present(self):
        names = {lyr["name"] for lyr in LAYERS}
        must_have = {
            "nwell", "pwell", "dnwell", "diff", "tap", "poly", "licon1",
            "npc", "li1", "mcon", "met1", "via", "met2", "via2",
            "met3", "via3", "met4", "via4", "met5", "pad",
            "areaid.standardc", "prBoundary",
        }
        missing = must_have - names
        self.assertFalse(missing, f"Missing expected layers: {missing}")

    def test_gds_layer_is_int(self):
        for lyr in LAYERS:
            self.assertIsInstance(lyr["gds_layer"], int,
                                  f"{lyr['name']}.gds_layer is not int")

    def test_gds_datatype_is_int(self):
        for lyr in LAYERS:
            self.assertIsInstance(lyr["gds_datatype"], int,
                                  f"{lyr['name']}.gds_datatype is not int")

    def test_color_is_hex_string(self):
        for lyr in LAYERS:
            self.assertRegex(lyr["color"], r"^#[0-9A-Fa-f]{6}$",
                             f"{lyr['name']}.color is not a hex color")

    def test_get_layer_known(self):
        lyr = get_layer("met1")
        self.assertIsNotNone(lyr)
        self.assertEqual(lyr["gds_layer"], 68)

    def test_get_layer_unknown_returns_none(self):
        self.assertIsNone(get_layer("does_not_exist"))

    def test_poly_layer_gds_layer(self):
        poly = get_layer("poly")
        self.assertIsNotNone(poly)
        self.assertEqual(poly["gds_layer"], 66)

    def test_met5_layer_present(self):
        self.assertIsNotNone(get_layer("met5"))

    def test_via4_present(self):
        self.assertIsNotNone(get_layer("via4"))


# ===========================================================================
# Standard-cell tests
# ===========================================================================

class TestStdCells(unittest.TestCase):
    def test_at_least_30_cells(self):
        self.assertGreaterEqual(len(STD_CELLS), 30)

    def test_each_cell_has_required_fields(self):
        required = {"name", "function", "drive_strength", "area_um2",
                    "leakage_pw", "ports"}
        for cell in STD_CELLS:
            missing = required - set(cell.keys())
            self.assertFalse(missing,
                              f"Cell {cell.get('name')} missing fields: {missing}")

    def test_all_names_are_sky130_fd_sc_hd(self):
        for cell in STD_CELLS:
            self.assertTrue(
                cell["name"].startswith("sky130_fd_sc_hd__"),
                f"{cell['name']} does not start with sky130_fd_sc_hd__",
            )

    def test_drive_strength_positive_int(self):
        for cell in STD_CELLS:
            self.assertIsInstance(cell["drive_strength"], int)
            self.assertGreater(cell["drive_strength"], 0)

    def test_area_um2_positive_float(self):
        for cell in STD_CELLS:
            self.assertGreater(cell["area_um2"], 0.0,
                               f"{cell['name']}.area_um2 <= 0")

    def test_ports_is_nonempty_list(self):
        for cell in STD_CELLS:
            self.assertIsInstance(cell["ports"], list)
            self.assertGreater(len(cell["ports"]), 0)

    def test_known_cells_present(self):
        names = {c["name"] for c in STD_CELLS}
        must_have = {
            "sky130_fd_sc_hd__inv_1",
            "sky130_fd_sc_hd__inv_2",
            "sky130_fd_sc_hd__inv_4",
            "sky130_fd_sc_hd__inv_8",
            "sky130_fd_sc_hd__nand2_1",
            "sky130_fd_sc_hd__nor2_1",
            "sky130_fd_sc_hd__xor2_1",
            "sky130_fd_sc_hd__dfxtp_1",
            "sky130_fd_sc_hd__dfrtp_1",
            "sky130_fd_sc_hd__mux2_1",
            "sky130_fd_sc_hd__a21o_1",
        }
        missing = must_have - names
        self.assertFalse(missing, f"Missing expected cells: {missing}")

    def test_get_cell_known(self):
        cell = get_cell("sky130_fd_sc_hd__inv_1")
        self.assertIsNotNone(cell)
        self.assertEqual(cell["drive_strength"], 1)

    def test_get_cell_unknown_returns_none(self):
        self.assertIsNone(get_cell("sky130_fd_sc_hd__does_not_exist"))

    def test_dfxtp_1_ports_include_clk_d_q(self):
        cell = get_cell("sky130_fd_sc_hd__dfxtp_1")
        self.assertIsNotNone(cell)
        for port in ("CLK", "D", "Q"):
            self.assertIn(port, cell["ports"],
                          f"dfxtp_1 missing port {port}")

    def test_no_duplicate_cell_names(self):
        names = [c["name"] for c in STD_CELLS]
        self.assertEqual(len(names), len(set(names)),
                         "Duplicate cell names detected")


# ===========================================================================
# Design-rule tests
# ===========================================================================

class TestDesignRules(unittest.TestCase):
    def test_at_least_20_rules(self):
        self.assertGreaterEqual(len(DESIGN_RULES), 20)

    def test_each_rule_has_required_fields(self):
        required = {"name", "layer", "rule_type", "description"}
        for rule in DESIGN_RULES:
            missing = required - set(rule.keys())
            self.assertFalse(missing,
                              f"Rule {rule.get('name')} missing fields: {missing}")

    def test_known_rules_present(self):
        names = {r["name"] for r in DESIGN_RULES}
        must_have = {
            "poly.width.min",
            "met1.width.min",
            "met1.spacing.min",
            "via.size.fixed",
            "nwell.spacing.same_potential",
        }
        missing = must_have - names
        self.assertFalse(missing, f"Missing expected rules: {missing}")

    def test_poly_width_min_value(self):
        rule = get_rule("poly.width.min")
        self.assertIsNotNone(rule)
        self.assertAlmostEqual(rule["value_um"], 0.150, places=3)

    def test_met1_width_min_value(self):
        rule = get_rule("met1.width.min")
        self.assertIsNotNone(rule)
        self.assertAlmostEqual(rule["value_um"], 0.140, places=3)

    def test_met1_spacing_min_value(self):
        rule = get_rule("met1.spacing.min")
        self.assertIsNotNone(rule)
        self.assertAlmostEqual(rule["value_um"], 0.140, places=3)

    def test_via_size_fixed_has_width_height(self):
        rule = get_rule("via.size.fixed")
        self.assertIsNotNone(rule)
        self.assertAlmostEqual(rule["width_um"], 0.150, places=3)
        self.assertAlmostEqual(rule["height_um"], 0.150, places=3)

    def test_nwell_same_potential_spacing(self):
        rule = get_rule("nwell.spacing.same_potential")
        self.assertIsNotNone(rule)
        self.assertAlmostEqual(rule["value_um"], 1.270, places=3)

    def test_rule_types_are_valid(self):
        valid_types = {
            "min_width", "min_spacing", "min_enclosure",
            "exact_size", "min_area", "same_potential_spacing",
        }
        for rule in DESIGN_RULES:
            self.assertIn(rule["rule_type"], valid_types,
                          f"{rule['name']} has unexpected rule_type {rule['rule_type']!r}")

    def test_get_rule_unknown_returns_none(self):
        self.assertIsNone(get_rule("nonexistent.rule"))


# ===========================================================================
# Installer tests
# ===========================================================================

class TestInstaller(unittest.TestCase):
    def test_is_pdk_available_false_when_env_unset(self):
        """When neither PDK_ROOT nor ~/.volare/sky130A is set, should be False."""
        # Save and unset PDK_ROOT so the env-variable path is not triggered.
        saved = os.environ.pop("PDK_ROOT", None)
        try:
            # We cannot control whether the test machine has ~/.volare/sky130A,
            # but we can at least confirm the function returns a bool.
            result = is_pdk_available()
            self.assertIsInstance(result, bool)

            # On a standard CI / developer machine without the PDK installed
            # and without PDK_ROOT set, this must return False.
            import pathlib
            volare = pathlib.Path.home() / ".volare" / "sky130A"
            if not volare.is_dir():
                self.assertFalse(
                    result,
                    "is_pdk_available() should return False when PDK is not present",
                )
        finally:
            if saved is not None:
                os.environ["PDK_ROOT"] = saved

    def test_is_pdk_available_returns_bool(self):
        self.assertIsInstance(is_pdk_available(), bool)

    def test_install_hint_mentions_volare(self):
        hint = install_hint()
        self.assertIn("volare", hint.lower())

    def test_install_hint_mentions_sky130a(self):
        hint = install_hint()
        self.assertIn("sky130A", hint)

    def test_install_hint_is_string(self):
        self.assertIsInstance(install_hint(), str)

    def test_install_hint_nonempty(self):
        self.assertTrue(len(install_hint()) > 0)


# ===========================================================================
# Top-level SKY130_PDK bundle test
# ===========================================================================

class TestSky130PdkBundle(unittest.TestCase):
    def test_bundle_has_name(self):
        self.assertEqual(SKY130_PDK["name"], "sky130A")

    def test_bundle_has_layers(self):
        self.assertIs(SKY130_PDK["layers"], LAYERS)

    def test_bundle_has_std_cells(self):
        self.assertIs(SKY130_PDK["std_cells"], STD_CELLS)

    def test_bundle_has_design_rules(self):
        self.assertIs(SKY130_PDK["design_rules"], DESIGN_RULES)

    def test_bundle_license_is_apache(self):
        self.assertIn("Apache", SKY130_PDK["license"])


if __name__ == "__main__":
    unittest.main()
