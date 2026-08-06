"""test_kicad_io_zones.py — T-526: KiCad zones/pours/keepouts read into Circuit JSON.

Fixture provenance (read before trusting these tests as "real board" evidence):
`tests/fixtures/zones_keepout_board.kicad_pcb` is **hand-authored**, not a pcbnew
export. It was written to match KiCad v6/v7's documented s-expression grammar for
`(zone ...)` (net-bound copper pour with thermal reliefs, a no-net ground-fill
zone, and a `(keepout ...)` rule area), plus a locked+attr footprint, a `gr_text`,
and a `group` — but no real copy of pcbnew ran to produce it. Treat these as
grammar-conformance tests, not proof that real-world KiCad output round-trips
identically; T-528 (round-trip conformance vectors) should re-verify against a
genuine pcbnew export when one becomes available.
"""

from __future__ import annotations

import os
import unittest

from kerf_electronics.kicad_io import kicad_pcb_to_circuit_json

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE_PATH = os.path.join(_HERE, "fixtures", "zones_keepout_board.kicad_pcb")

with open(_FIXTURE_PATH, encoding="utf-8") as _f:
    _FIXTURE_TEXT = _f.read()


class TestZonesAndKeepouts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cj = kicad_pcb_to_circuit_json(_FIXTURE_TEXT)

    def _by_type(self, t):
        return [e for e in self.cj if e.get("type") == t]

    # ── copper pour (net-bound zone) ─────────────────────────────────────────

    def test_one_copper_pour_recovered(self):
        pours = self._by_type("pcb_copper_pour")
        self.assertEqual(len(pours), 1, pours)

    def test_copper_pour_net_and_layer(self):
        pour = self._by_type("pcb_copper_pour")[0]
        self.assertEqual(pour["net_id"], "GND")
        self.assertEqual(pour["net_index"], 1)
        self.assertEqual(pour["layer"], "bottom_copper")

    def test_copper_pour_polygon_outline(self):
        """T-538: this used to assert {"x": 100.0, "y": 80.0} — the raw
        KiCad Y-down outline coordinate passed straight through, unflipped.
        That was the bug the fixture happened to pin: the zone's fixture
        text (`tests/fixtures/zones_keepout_board.kicad_pcb`) authors this
        vertex as KiCad `(xy 100 80)`, and kicad_io.py now correctly emits
        it as Circuit JSON's Y-up `{"x": 100.0, "y": -80.0}` (see
        `_flip_kicad_y_to_circuit_json_y` in kicad_io.py). The old value was
        wrong, not this one — updating it is fixing the bug's fingerprint,
        not relabeling it."""
        pour = self._by_type("pcb_copper_pour")[0]
        self.assertEqual(len(pour["polygon"]), 4)
        self.assertEqual(pour["polygon"][0], {"x": 0.0, "y": 0.0})
        self.assertEqual(pour["polygon"][2], {"x": 100.0, "y": -80.0})

    def test_copper_pour_fill_settings(self):
        pour = self._by_type("pcb_copper_pour")[0]
        self.assertEqual(pour["priority"], 1)
        self.assertEqual(pour["clearance_mm"], 0.2)
        self.assertEqual(pour["min_thickness_mm"], 0.1)
        self.assertEqual(pour["thermal_relief"], {"gap": 0.2, "spoke_width": 0.3})

    def test_copper_pour_unmodelled_children_preserved(self):
        """`filled_polygon` and `hatch` aren't modelled — must survive verbatim."""
        pour = self._by_type("pcb_copper_pour")[0]
        passthrough = pour.get("_kicad_passthrough", [])
        tags = {node[0] for node in passthrough}
        self.assertIn("filled_polygon", tags)
        self.assertIn("hatch", tags)

    # ── ground plane (no-net zone) ───────────────────────────────────────────

    def test_one_ground_plane_recovered(self):
        planes = self._by_type("pcb_ground_plane")
        self.assertEqual(len(planes), 1, planes)

    def test_ground_plane_has_no_net_id(self):
        plane = self._by_type("pcb_ground_plane")[0]
        self.assertNotIn("net_id", plane)

    def test_ground_plane_inner_layer_mapped(self):
        plane = self._by_type("pcb_ground_plane")[0]
        self.assertEqual(plane["layer"], "inner_1")

    def test_ground_plane_polygon_outline(self):
        plane = self._by_type("pcb_ground_plane")[0]
        self.assertEqual(len(plane["polygon"]), 4)

    # ── keepout zone ──────────────────────────────────────────────────────────

    def test_one_keepout_recovered(self):
        keepouts = self._by_type("pcb_keepout")
        self.assertEqual(len(keepouts), 1, keepouts)

    def test_keepout_restriction_flags(self):
        ko = self._by_type("pcb_keepout")[0]
        self.assertTrue(ko["no_tracks"])
        self.assertTrue(ko["no_vias"])
        self.assertTrue(ko["no_pads"])
        self.assertTrue(ko["no_copperpour"])
        self.assertFalse(ko["no_footprints"])
        # base pcb_keepout shape (autoplace/essentials.py) fields also present
        self.assertTrue(ko["no_routing"])
        self.assertFalse(ko["no_components"])

    def test_keepout_layer_and_shape(self):
        ko = self._by_type("pcb_keepout")[0]
        self.assertEqual(ko["layer"], "top_copper")
        self.assertEqual(ko["shape"], "polygon")
        self.assertEqual(len(ko["polygon"]), 4)

    def test_keepout_has_no_fill_settings(self):
        """Keepouts never fill — priority/clearance/thermal_relief don't apply."""
        ko = self._by_type("pcb_keepout")[0]
        self.assertNotIn("priority", ko)
        self.assertNotIn("thermal_relief", ko)

    # ── locked flag + footprint attributes ───────────────────────────────────

    def test_footprint_locked_flag(self):
        comps = self._by_type("pcb_component")
        self.assertEqual(len(comps), 1)
        self.assertTrue(comps[0].get("locked"))

    # ── T-538: absolute position, not merely self-consistent ────────────────
    #
    # The bug this guards against is invisible to any test that only checks
    # internal consistency (e.g. a pour's vias landing inside its own
    # bounding box) — a whole-file mirror is self-consistent with itself.
    # This test instead hand-computes the expected Circuit JSON position
    # directly from the fixture's own KiCad source text, independent of
    # kicad_io.py, so it fails if the flip axis (or its sign) is wrong even
    # though everything *else* in the file still lines up with everything
    # else.

    def test_footprint_lands_at_correct_absolute_position_not_just_self_consistent(self):
        """Ground truth, read directly from
        tests/fixtures/zones_keepout_board.kicad_pcb line 26: the only
        footprint on this board is authored as `(at 10 10)` — KiCad
        Y-down, so 10mm to the right of and 10mm *below* the sheet origin.
        Circuit JSON is Y-up, so the correct absolute position is
        (10, -10): x is unaffected by the flip (KiCad and Circuit JSON
        agree on the X direction), y is negated about the fixed origin
        kicad_io.py's flip uses (see `_flip_kicad_y_to_circuit_json_y` in
        kicad_io.py) — not (10, 10) (the old, unflipped bug) and not some
        other value a board-bbox-relative or page-relative axis would have
        produced.
        """
        comps = self._by_type("pcb_component")
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0]["x"], 10.0)
        self.assertEqual(comps[0]["y"], -10.0)

    def test_footprint_attributes(self):
        comps = self._by_type("pcb_component")
        attrs = comps[0]["kicad_footprint_attributes"]
        self.assertTrue(attrs["smd"])
        self.assertFalse(attrs["through_hole"])
        self.assertTrue(attrs["exclude_from_bom"])
        self.assertFalse(attrs["exclude_from_pos_files"])

    # ── gr_text ──────────────────────────────────────────────────────────────

    def test_gr_text_recovered_as_pcb_text(self):
        """T-538: this used to assert y == 75.0 — the fixture's raw KiCad
        `(at 5 75 0)` passed straight through unflipped. kicad_io.py now
        emits Circuit JSON's Y-up `y == -75.0` (x is unaffected by the
        flip). The old value encoded the mirror bug, not a real
        expectation."""
        texts = self._by_type("pcb_text")
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0]["text"], "REV A")
        self.assertEqual(texts[0]["x"], 5.0)
        self.assertEqual(texts[0]["y"], -75.0)
        self.assertEqual(texts[0]["layer"], "Cmts.User")

    # ── passthrough for unmodelled top-level nodes (group) ───────────────────

    def test_group_preserved_in_passthrough(self):
        passthroughs = self._by_type("kicad_passthrough")
        self.assertEqual(len(passthroughs), 1)
        nodes = passthroughs[0]["kicad_nodes"]
        tags = {n[0] for n in nodes if isinstance(n, list) and n}
        self.assertIn("group", tags)

    # ── existing baseline (footprint/net/trace) still recovered alongside ───

    def test_existing_recovery_unaffected(self):
        self.assertEqual(len(self._by_type("source_component")), 1)
        self.assertEqual(len(self._by_type("pcb_trace")), 1)
        nets = {n["name"] for n in self._by_type("source_net")}
        self.assertIn("GND", nets)
        self.assertIn("VCC", nets)


class TestEmptyAndMalformedZonesSafe(unittest.TestCase):
    """Zone parsing must degrade gracefully, matching the file's existing
    fail-open conventions (never raise on malformed input)."""

    def test_zone_with_no_polygon(self):
        text = '(kicad_pcb (zone (net 1) (net_name "GND") (layer "F.Cu")))'
        cj = kicad_pcb_to_circuit_json(text)
        pours = [e for e in cj if e.get("type") == "pcb_copper_pour"]
        self.assertEqual(len(pours), 1)
        self.assertEqual(pours[0]["polygon"], [])

    def test_zone_with_no_net_and_no_keepout_is_ground_plane(self):
        text = '(kicad_pcb (zone (net 0) (net_name "") (layer "F.Cu")))'
        cj = kicad_pcb_to_circuit_json(text)
        planes = [e for e in cj if e.get("type") == "pcb_ground_plane"]
        self.assertEqual(len(planes), 1)


if __name__ == "__main__":
    unittest.main()
