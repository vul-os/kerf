"""test_t527_kicad_writer.py — T-527: KiCad writer (Circuit JSON -> .kicad_pcb).

The payoff of T-526/T-536/T-538/T-539: `circuit_json_to_kicad_pcb` is now the
inverse of `kicad_pcb_to_circuit_json` across everything the reader models —
footprints (position/rotation/locked/attrs), nets/traces, zones (copper
pours, ground planes, keepouts, thermal reliefs), free-floating text, and,
critically, the passthrough bag: nodes the reader could not model (here, a
`group`) are carried through unmodified and re-emitted so a second read
recovers them again.

Two independent checks, per the task's Definition of Done:

1. **Self round-trip** (`TestRoundTripSelfConsistent`): read ->
   write -> read again, using *only* this module's own reader. Semantic
   equality (element-for-element field equality, not byte-identical text —
   KiCad's grammar has many equally-valid renderings), not `assertEqual`
   equality on raw text.

2. **Oracle agreement** (`TestWrittenFileAgreesWithOracle`): the file this
   writer produces must actually be re-parseable by the independent
   `kicad-to-circuit-json` oracle (T-526b) — not just by our own lenient
   reader — and the two must agree on what they can both see, the same way
   `test_kicad_oracle.py` holds the *reader* to that standard. This is the
   check that catches a writer that only looks correct because it is only
   ever re-read by the same code that wrote it (the exact self-consistency
   trap `tasks.md`'s G2 preamble calls out — T-538 hid for a release
   because nothing but the reader itself ever looked at its output).

Passing (1) alone would only prove self-consistency; (2) is what makes this
program's oracle discipline apply to the writer as well as the reader, per
this task's explicit instruction not to repeat that mistake.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from kerf_electronics.kicad_io import (
    circuit_json_to_kicad_pcb,
    kicad_pcb_to_circuit_json,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ZONES_FIXTURE_PATH = os.path.join(_HERE, "fixtures", "zones_keepout_board.kicad_pcb")
_OUTLINE_FIXTURE_PATH = os.path.join(_HERE, "fixtures", "board_with_outline.kicad_pcb")
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ORACLE_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "kicad_oracle_convert.mjs")

with open(_ZONES_FIXTURE_PATH, encoding="utf-8") as _f:
    _ZONES_FIXTURE_TEXT = _f.read()

with open(_OUTLINE_FIXTURE_PATH, encoding="utf-8") as _f:
    _OUTLINE_FIXTURE_TEXT = _f.read()


def _id_key(e: dict) -> tuple:
    """A stable sort/compare key for a Circuit-JSON element: its own
    id-shaped field if it has one, else the whole dict's sorted items."""
    for id_field in (
        "pcb_copper_pour_id", "pcb_ground_plane_id", "pcb_keepout_id",
        "pcb_component_id", "pcb_text_id", "pcb_trace_id",
        "source_net_id", "source_component_id", "source_trace_id",
    ):
        if id_field in e:
            return (e.get("type"), e[id_field])
    return (e.get("type"), json.dumps(e, sort_keys=True))


def _strip_top_level_group(kicad_pcb_text: str) -> str:
    """Remove the top-level ``(group ...)`` node by paren-depth counting.

    Same workaround as test_kicad_oracle.py: kicadts hard-crashes on a
    spec-correct `(group "NAME" (id UUID) (members ...))` node (a real
    compliance gap in the oracle's own parser, not in kerf). Stripping it
    here only affects the copy handed to the oracle; the un-stripped text is
    what this module's own reader parses throughout this test.
    """
    idx = kicad_pcb_text.find("(group")
    if idx == -1:
        return kicad_pcb_text
    depth = 0
    i = idx
    n = len(kicad_pcb_text)
    while i < n:
        ch = kicad_pcb_text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                i += 1
                break
        i += 1
    return kicad_pcb_text[:idx] + kicad_pcb_text[i:]


def _run_oracle_converter(kicad_pcb_text: str) -> list:
    """Run kicad-to-circuit-json over *kicad_pcb_text*; return its output.

    Hard failure, never a skip, if Node or the package is unavailable — see
    test_kicad_oracle.py's module docstring and tasks.md's T-550 cautionary
    tale about `pytest.importorskip` masking a check that never runs.
    """
    node = shutil.which("node")
    if node is None:
        raise RuntimeError(
            "T-527 oracle check requires Node.js on PATH. Not found: this "
            "is a hard test failure, not a skip."
        )
    if not os.path.exists(_ORACLE_SCRIPT):
        raise RuntimeError(f"oracle helper script missing: {_ORACLE_SCRIPT}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(kicad_pcb_text)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            [node, _ORACLE_SCRIPT, tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=_REPO_ROOT,
        )
    finally:
        os.unlink(tmp_path)

    if proc.returncode != 0:
        raise RuntimeError(
            "T-527 oracle check (kicad-to-circuit-json) failed "
            f"(exit {proc.returncode}) — hard failure, not a skip. "
            f"stderr:\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


class TestRoundTripSelfConsistent(unittest.TestCase):
    """read -> write -> read, using only kerf's own reader. The two Circuit
    JSON results must be semantically identical — same elements, same
    fields — not merely the same *count* of each type."""

    @classmethod
    def setUpClass(cls):
        cls.cj1 = kicad_pcb_to_circuit_json(_ZONES_FIXTURE_TEXT)
        cls.written = circuit_json_to_kicad_pcb(cls.cj1)
        cls.cj2 = kicad_pcb_to_circuit_json(cls.written)

    def test_written_output_has_balanced_parens(self):
        self.assertEqual(self.written.count("("), self.written.count(")"))

    def test_same_element_count(self):
        self.assertEqual(len(self.cj1), len(self.cj2),
                          f"cj1={[e.get('type') for e in self.cj1]}\n"
                          f"cj2={[e.get('type') for e in self.cj2]}")

    def test_semantically_identical(self):
        """Every element, compared field-for-field (dict equality),
        regardless of list order."""
        s1 = sorted(self.cj1, key=_id_key)
        s2 = sorted(self.cj2, key=_id_key)
        self.assertEqual(s1, s2)

    # ── individual constructs, called out explicitly per the task's DoD ────

    def test_footprint_position_rotation_locked_attrs_round_trip(self):
        c1 = next(e for e in self.cj1 if e["type"] == "pcb_component")
        c2 = next(e for e in self.cj2 if e["type"] == "pcb_component")
        self.assertEqual(c1["x"], c2["x"])
        self.assertEqual(c1["y"], c2["y"])
        self.assertEqual(c1["rotation"], c2["rotation"])
        self.assertEqual(c1.get("locked"), c2.get("locked"))
        self.assertTrue(c1.get("locked"))  # the fixture's footprint IS locked
        self.assertEqual(
            c1["kicad_footprint_attributes"], c2["kicad_footprint_attributes"]
        )

    def test_copper_pour_thermal_relief_round_trips(self):
        p1 = next(e for e in self.cj1 if e["type"] == "pcb_copper_pour")
        p2 = next(e for e in self.cj2 if e["type"] == "pcb_copper_pour")
        self.assertEqual(p1["thermal_relief"], p2["thermal_relief"])
        self.assertEqual(p1["priority"], p2["priority"])
        self.assertEqual(p1["clearance_mm"], p2["clearance_mm"])
        self.assertEqual(p1["min_thickness_mm"], p2["min_thickness_mm"])
        self.assertEqual(p1["polygon"], p2["polygon"])
        self.assertEqual(p1["net_id"], p2["net_id"])

    def test_ground_plane_round_trips(self):
        g1 = next(e for e in self.cj1 if e["type"] == "pcb_ground_plane")
        g2 = next(e for e in self.cj2 if e["type"] == "pcb_ground_plane")
        self.assertEqual(g1["layer"], g2["layer"])
        self.assertEqual(g1["polygon"], g2["polygon"])
        self.assertNotIn("net_id", g2)

    def test_keepout_restriction_flags_round_trip(self):
        k1 = next(e for e in self.cj1 if e["type"] == "pcb_keepout")
        k2 = next(e for e in self.cj2 if e["type"] == "pcb_keepout")
        for flag in ("no_tracks", "no_vias", "no_pads", "no_copperpour",
                     "no_footprints", "no_routing", "no_components"):
            self.assertEqual(k1[flag], k2[flag], flag)
        self.assertEqual(k1["polygon"], k2["polygon"])
        self.assertEqual(k1["layer"], k2["layer"])

    def test_gr_text_round_trips(self):
        t1 = next(e for e in self.cj1 if e["type"] == "pcb_text")
        t2 = next(e for e in self.cj2 if e["type"] == "pcb_text")
        self.assertEqual(t1["text"], t2["text"])
        self.assertEqual(t1["x"], t2["x"])
        self.assertEqual(t1["y"], t2["y"])
        self.assertEqual(t1["layer"], t2["layer"])

    def test_trace_round_trips(self):
        tr1 = next(e for e in self.cj1 if e["type"] == "pcb_trace")
        tr2 = next(e for e in self.cj2 if e["type"] == "pcb_trace")
        self.assertEqual(tr1["route"], tr2["route"])
        self.assertEqual(tr1["width"], tr2["width"])
        self.assertEqual(tr1["layer"], tr2["layer"])

    # ── passthrough: the actual point of this task ──────────────────────────

    def test_passthrough_group_node_survives_two_full_cycles(self):
        """The fixture's `(group "power_zone" ...)` node is not modelled by
        the reader at all — it must come back out of *both* reads, byte-for-
        value identical, as `kicad_passthrough`."""
        pt1 = next(e for e in self.cj1 if e["type"] == "kicad_passthrough")
        pt2 = next(e for e in self.cj2 if e["type"] == "kicad_passthrough")
        groups1 = [n for n in pt1["kicad_nodes"] if n[0] == "group"]
        groups2 = [n for n in pt2["kicad_nodes"] if n[0] == "group"]
        self.assertEqual(len(groups1), 1)
        self.assertEqual(len(groups2), 1)
        self.assertEqual(groups1[0], groups2[0])
        # And the group's own content — name, id, member UUIDs — must be
        # exactly what the source fixture authored, not just "a group".
        self.assertEqual(groups1[0][1], "power_zone")

    def test_zone_level_passthrough_hatch_and_filled_polygon_survive(self):
        """`hatch` and `filled_polygon` are unmodelled *inside* a zone
        (T-526's `_kicad_passthrough`, distinct from the top-level
        `kicad_passthrough` bag) — must also survive two cycles."""
        p1 = next(e for e in self.cj1 if e["type"] == "pcb_copper_pour")
        p2 = next(e for e in self.cj2 if e["type"] == "pcb_copper_pour")
        tags1 = {n[0] for n in p1.get("_kicad_passthrough", [])}
        tags2 = {n[0] for n in p2.get("_kicad_passthrough", [])}
        self.assertIn("hatch", tags1)
        self.assertIn("filled_polygon", tags1)
        self.assertEqual(tags1, tags2)


class TestOutlineFixtureRoundTrip(unittest.TestCase):
    """Second fixture — no zones, but a genuine Edge.Cuts outline (gr_line,
    unmodelled -> passthrough) and a footprint with no locked/attr flags.
    Exercises the writer's passthrough path on plain gr_line nodes and
    confirms the T-539 fixed-origin convention round-trips through the
    writer too (not just the reader)."""

    @classmethod
    def setUpClass(cls):
        cls.cj1 = kicad_pcb_to_circuit_json(_OUTLINE_FIXTURE_TEXT)
        cls.written = circuit_json_to_kicad_pcb(cls.cj1)
        cls.cj2 = kicad_pcb_to_circuit_json(cls.written)

    def test_semantically_identical(self):
        s1 = sorted(self.cj1, key=_id_key)
        s2 = sorted(self.cj2, key=_id_key)
        self.assertEqual(s1, s2)

    def test_footprint_position_matches_fixed_origin_convention(self):
        """Ground truth: fixture authors `(at 70 60)` (KiCad Y-down) — see
        test_kicad_oracle.py's TestKicadOracleOutlineConvention for the same
        fixture read directly. Both read passes must agree at (70, -60)."""
        c1 = next(e for e in self.cj1 if e["type"] == "pcb_component")
        c2 = next(e for e in self.cj2 if e["type"] == "pcb_component")
        self.assertAlmostEqual(c1["x"], 70.0, places=6)
        self.assertAlmostEqual(c1["y"], -60.0, places=6)
        self.assertAlmostEqual(c2["x"], 70.0, places=6)
        self.assertAlmostEqual(c2["y"], -60.0, places=6)

    def test_edge_cuts_outline_passthrough_survives(self):
        pt1 = next(e for e in self.cj1 if e["type"] == "kicad_passthrough")
        pt2 = next(e for e in self.cj2 if e["type"] == "kicad_passthrough")
        gr_lines1 = [n for n in pt1["kicad_nodes"] if n[0] == "gr_line"]
        gr_lines2 = [n for n in pt2["kicad_nodes"] if n[0] == "gr_line"]
        self.assertEqual(len(gr_lines1), 4)  # rectangle outline
        self.assertEqual(gr_lines1, gr_lines2)


class TestWrittenFileAgreesWithOracle(unittest.TestCase):
    """The file `circuit_json_to_kicad_pcb` writes must itself be readable
    by the independent `kicad-to-circuit-json` oracle, and the oracle's
    reading of *our own written file* must agree with our own reader's
    second pass over that same file — the writer-side counterpart of
    test_kicad_oracle.py holding the reader to independent scrutiny.
    """

    @classmethod
    def setUpClass(cls):
        cls.cj1 = kicad_pcb_to_circuit_json(_ZONES_FIXTURE_TEXT)
        cls.written = circuit_json_to_kicad_pcb(cls.cj1)
        cls.cj2 = kicad_pcb_to_circuit_json(cls.written)
        sanitized = _strip_top_level_group(cls.written)
        cls.oracle = _run_oracle_converter(sanitized)

    def test_oracle_parses_the_written_file_at_all(self):
        """The headline check: a writer whose only reader is itself proves
        nothing (tasks.md's G2 preamble). This fails loudly, not silently,
        if the oracle chokes on our output."""
        self.assertGreater(len(self.oracle), 0)

    def test_component_position_agrees_with_oracle(self):
        """Fixed-origin convention (T-538/T-539): both should read the
        written footprint at KiCad (10, 10) -> CJ (10.0, -10.0)."""
        ours = next(e for e in self.cj2 if e["type"] == "pcb_component")
        oracle = next(e for e in self.oracle if e["type"] == "pcb_component")
        self.assertAlmostEqual(ours["x"], 10.0, places=6)
        self.assertAlmostEqual(ours["y"], -10.0, places=6)
        self.assertAlmostEqual(oracle["center"]["x"], ours["x"], places=6)
        self.assertAlmostEqual(oracle["center"]["y"], ours["y"], places=6)

    def test_net_bound_pour_agrees_with_oracle(self):
        ours = next(e for e in self.cj2 if e["type"] == "pcb_copper_pour")
        oracle_matches = [
            e for e in self.oracle
            if e["type"] == "pcb_copper_pour" and e.get("net_name")
        ]
        self.assertEqual(len(oracle_matches), 1)
        oracle = oracle_matches[0]
        self.assertEqual(oracle["net_name"], ours["net_id"])
        # kerf: "bottom_copper" <-> oracle: "bottom" (T-536's frozen naming,
        # same mapping test_kicad_oracle.py uses).
        self.assertEqual(oracle["layer"], "bottom")
        self.assertEqual(ours["layer"], "bottom_copper")

    def test_ground_plane_agrees_with_oracle_as_a_no_net_pour(self):
        """Same documented, deliberate divergence test_kicad_oracle.py
        pins for the reader: kerf types a no-net zone as `pcb_ground_plane`;
        the oracle types every zone as `pcb_copper_pour` with an empty
        `net_name`. Verdict there was "ours is right" — unchanged here."""
        ours = next(e for e in self.cj2 if e["type"] == "pcb_ground_plane")
        oracle_matches = [
            e for e in self.oracle
            if e["type"] == "pcb_copper_pour" and not e.get("net_name")
        ]
        self.assertEqual(len(oracle_matches), 1)
        oracle = oracle_matches[0]
        self.assertEqual(oracle["layer"], "inner1")
        self.assertEqual(ours["layer"], "inner_1")

    def test_keepout_remains_a_documented_oracle_scope_gap_not_a_writer_bug(self):
        """kicad-to-circuit-json's CollectZonesStage never emits
        `pcb_keepout` at all (test_kicad_oracle.py pins the same gap for the
        reader's fixture) — our writer faithfully reproduces a real KiCad
        `(zone (keepout ...))` node; the oracle simply doesn't model the
        construct, on written output same as on hand-authored input."""
        ours_keepout = next(e for e in self.cj2 if e["type"] == "pcb_keepout")
        self.assertIsNotNone(ours_keepout)
        oracle_types = {e["type"] for e in self.oracle}
        self.assertNotIn("pcb_keepout", oracle_types)


if __name__ == "__main__":
    unittest.main()
