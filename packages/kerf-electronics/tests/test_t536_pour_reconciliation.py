"""test_t536_pour_reconciliation.py — T-536: reconcile Kerf's pour conventions.

Before this task Kerf had >=3 incompatible in-repo pour conventions (see
tasks.md T-536): a flat Circuit-JSON array (`pcb_copper_pour` /
`copper_pour_fill`, read by fab/gerber.py and fab/odbpp/writer.py), a
board-level dict (`board['copper_pour']`, keyed by `pour_id`, read by
tools/via_stitching.py), and tools/pour.py's/the frontend's own shapes.
`pcb_ground_plane` (T-526's no-net zone) had no downstream reader at all.

This is the end-to-end proof, not a nice-to-have: read a real pour out of a
KiCad board, then feed the *same* flat Circuit-JSON list — with no
per-consumer translation step in between — into Gerber, ODB++, and
via-stitching. All three must consume the identical `pcb_copper_pour` /
`pcb_ground_plane` element(s) T-526's reader already produces.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import tarfile
import unittest

from kerf_electronics.kicad_io import kicad_pcb_to_circuit_json
from kerf_electronics.fab.gerber import export_gerber
from kerf_electronics.fab.gerber import _classify_elements as _gerber_classify
from kerf_electronics.fab.odbpp.writer import export_odbpp
from kerf_electronics.fab.odbpp.writer import _classify_elements as _odbpp_classify
from kerf_electronics.tools import via_stitching

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE_PATH = os.path.join(_HERE, "fixtures", "zones_keepout_board.kicad_pcb")

with open(_FIXTURE_PATH, encoding="utf-8") as _f:
    _FIXTURE_TEXT = _f.read()


def _run(coro):
    return asyncio.run(coro)


class TestPourReachesAllConsumersUnchanged(unittest.TestCase):
    """One `kicad_pcb_to_circuit_json` read, then the *same* list object goes
    straight into every consumer — no adapter, no re-shaping."""

    @classmethod
    def setUpClass(cls):
        cls.cj = kicad_pcb_to_circuit_json(_FIXTURE_TEXT)
        cls.pour = next(e for e in cls.cj if e["type"] == "pcb_copper_pour")
        cls.ground_plane = next(e for e in cls.cj if e["type"] == "pcb_ground_plane")

    # ── sanity: the fixture actually carries what this test depends on ──────

    def test_fixture_has_net_bound_pour_and_no_net_ground_plane(self):
        self.assertEqual(self.pour["net_id"], "GND")
        self.assertEqual(self.pour["layer"], "bottom_copper")
        self.assertNotIn("net_id", self.ground_plane)
        self.assertEqual(self.ground_plane["layer"], "inner_1")

    # ── Gerber (fab/gerber.py) ───────────────────────────────────────────────

    def test_gerber_classifies_both_pour_and_ground_plane(self):
        classified = _gerber_classify(self.cj)
        types = {e["type"] for e in classified["copper_pour"]}
        self.assertEqual(types, {"pcb_copper_pour", "pcb_ground_plane"})

    def test_gerber_emits_pour_region_unchanged(self):
        files = export_gerber(self.cj, stem="t536gerber")
        gbl = files["t536gerber.GBL"]  # bottom_copper
        self.assertIn("G36*", gbl)
        self.assertIn("G37*", gbl)
        # Exact vertex from the pour's own `polygon` field (100, 80) mm, in
        # Gerber's 4.6 integer format — no re-derivation, no translation.
        self.assertIn(f"X{100 * 1_000_000}Y{80 * 1_000_000}", gbl)

    def test_gerber_emits_ground_plane_on_its_inner_layer(self):
        files = export_gerber(self.cj, stem="t536gerber2")
        self.assertIn("t536gerber2.GL2", files)  # inner_1 -> GL2
        self.assertIn("G36*", files["t536gerber2.GL2"])

    # ── ODB++ (fab/odbpp/writer.py) ─────────────────────────────────────────

    def test_odbpp_classifies_both_pour_and_ground_plane(self):
        classified = _odbpp_classify(self.cj)
        types = {e["type"] for e in classified["copper_pour"]}
        self.assertEqual(types, {"pcb_copper_pour", "pcb_ground_plane"})

    def test_odbpp_emits_pour_surface_unchanged(self):
        result = export_odbpp(self.cj, stem="t536odbpp")
        tf = tarfile.open(fileobj=io.BytesIO(result["tgz_bytes"]), mode="r:gz")
        feat = tf.extractfile(
            tf.getmember("t536odbpp/steps/pcb/layers/bottom_copper/features")
        ).read().decode()
        self.assertIn("S P;", feat)
        self.assertIn("OB ", feat)
        self.assertIn("OE;", feat)
        # Same (100, 80) mm vertex from the pour's own polygon, unchanged.
        self.assertIn("100.000000", feat)
        self.assertIn("80.000000", feat)

    # ── via stitching (tools/via_stitching.py) ──────────────────────────────

    def test_via_stitching_resolves_the_same_pour_by_canonical_id(self):
        """T-536's headline fix: via_stitching used to only understand
        board['copper_pour'] keyed by pour_id — a shape the KiCad reader
        never produces. It must now resolve the pour directly out of the
        flat array by pcb_copper_pour_id, with no adapter step."""
        pour_id = self.pour["pcb_copper_pour_id"]
        args = json.dumps({
            "circuit_json": self.cj,
            "pour_id_or_polygon": pour_id,
            "pitch_mm": 20,
            "net_id": "GND",
            "strategy": "grid",
            "via_spec": {"diameter": 0.8, "drill": 0.4},
        }).encode()

        result = _run(via_stitching.add_via_stitching(None, args))
        data = json.loads(result)
        self.assertNotIn("error", data)
        new_cj = data["circuit_json"]

        vias = [e for e in new_cj if e.get("type") == "pcb_via" and e.get("pour_id") == pour_id]
        self.assertGreater(len(vias), 0)

        # Vias must fall inside the *same* polygon bounding box the pour
        # element carries — proof the stitching read the pour's actual
        # geometry, not a re-derived or translated copy of it.
        xs = [p["x"] for p in self.pour["polygon"]]
        ys = [p["y"] for p in self.pour["polygon"]]
        for v in vias:
            self.assertGreaterEqual(v["x"], min(xs) - 1e-6)
            self.assertLessEqual(v["x"], max(xs) + 1e-6)
            self.assertGreaterEqual(v["y"], min(ys) - 1e-6)
            self.assertLessEqual(v["y"], max(ys) + 1e-6)

        # Original circuit_json is untouched (the tool deep-copies).
        self.assertNotIn(
            "pcb_via_stitching",
            {e.get("type") for e in self.cj if isinstance(e, dict)},
        )

    def test_via_stitching_unknown_pour_id_errors(self):
        args = json.dumps({
            "circuit_json": self.cj,
            "pour_id_or_polygon": "does_not_exist",
            "pitch_mm": 20,
            "net_id": "GND",
            "strategy": "grid",
            "via_spec": {"diameter": 0.8, "drill": 0.4},
        }).encode()
        data = json.loads(_run(via_stitching.add_via_stitching(None, args)))
        self.assertIn("error", data)

    def test_via_stitching_can_target_the_ground_plane_too(self):
        """pcb_ground_plane has no net_id of its own, but it's still a valid
        stitching target (the tool's own net_id argument supplies the via
        net) — proof the reconciliation didn't special-case the net-bound
        pour at the ground plane's expense."""
        gp_id = self.ground_plane["pcb_ground_plane_id"]
        args = json.dumps({
            "circuit_json": self.cj,
            "pour_id_or_polygon": gp_id,
            "pitch_mm": 20,
            "net_id": "GND",
            "strategy": "grid",
            "via_spec": {"diameter": 0.8, "drill": 0.4},
        }).encode()
        data = json.loads(_run(via_stitching.add_via_stitching(None, args)))
        self.assertNotIn("error", data)
        vias = [e for e in data["circuit_json"]
                if e.get("type") == "pcb_via" and e.get("pour_id") == gp_id]
        self.assertGreater(len(vias), 0)

    def test_via_stitching_remove_undoes_it_cleanly(self):
        pour_id = self.pour["pcb_copper_pour_id"]
        add_args = json.dumps({
            "circuit_json": self.cj,
            "pour_id_or_polygon": pour_id,
            "pitch_mm": 20,
            "net_id": "GND",
            "strategy": "grid",
            "via_spec": {"diameter": 0.8, "drill": 0.4},
        }).encode()
        added = json.loads(_run(via_stitching.add_via_stitching(None, add_args)))
        cj_with_vias = added["circuit_json"]
        self.assertGreater(
            len([e for e in cj_with_vias if e.get("type") == "pcb_via"]), 0
        )

        remove_args = json.dumps({
            "circuit_json": cj_with_vias,
            "pour_id": pour_id,
        }).encode()
        removed = json.loads(_run(via_stitching.remove_via_stitching(None, remove_args)))
        cj_after = removed["circuit_json"]
        self.assertEqual(len([e for e in cj_after if e.get("type") == "pcb_via"]), 0)
        self.assertEqual(len([e for e in cj_after if e.get("type") == "pcb_via_stitching"]), 0)
        # The original pour element itself is untouched.
        pour_after = next(e for e in cj_after if e["type"] == "pcb_copper_pour")
        self.assertEqual(pour_after["polygon"], self.pour["polygon"])


if __name__ == "__main__":
    unittest.main()
