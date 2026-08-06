"""test_kicad_oracle.py — T-526b: CI conformance oracle for kicad_io.py.

Kerf's KiCad fixtures are hand-authored, not pcbnew exports (`docs/
ecad-gap-analysis.md` says so plainly) — the main weakness in the evidence
behind G2's reader work. This test closes that gap the honest way: it runs a
second, genuinely independent implementation of the same KiCad -> Circuit
JSON transform (`kicad-to-circuit-json`, MIT, tscircuit — see
node_modules/kicad-to-circuit-json, declared as a root devDependency) over
the same fixture `kicad_io.py`'s own tests use, and compares.

The two implementations disagree in several places. Each disagreement below
is investigated, not assumed away — see each test's docstring for the
verdict. One disagreement was a genuine, documented finding that became its
own follow-up task: the Y-axis convention (see
test_component_position_agrees_with_axis_convention) was pinned here as a
divergence by T-526b and is now *fixed* by T-538 in kicad_io.py itself — the
assertion below is a straight equality check, not equality-modulo-flip.
Another remains open and out of scope here: the oracle's own parser
(`kicadts`) has a real compliance gap against KiCad's documented `group`
node format (see test_oracle_chokes_on_kicads_own_documented_group_id_field).
This test does not silently paper over either, and beyond the T-538 axis fix
it does not otherwise change kicad_io.py's *behaviour* — T-526b's scope was
the lexer swap (a separate commit) and this oracle; T-538's scope is
narrowly the coordinate flip, not a rewrite of the frozen T-526 semantic
mapping.

This is a **required** check, never a skip: `_run_oracle_converter` raises
(not `pytest.importorskip`) if Node or the `kicad-to-circuit-json` package
is unavailable. `pytest.importorskip`-style silent skipping is exactly what
let T-550's only third-party check pass in CI while never running — see
tasks.md T-550.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from kerf_electronics.kicad_io import kicad_pcb_to_circuit_json

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE_PATH = os.path.join(_HERE, "fixtures", "zones_keepout_board.kicad_pcb")
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ORACLE_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "kicad_oracle_convert.mjs")

with open(_FIXTURE_PATH, encoding="utf-8") as _f:
    _FIXTURE_TEXT = _f.read()

# KiCad canonical layer name -> the oracle's Circuit JSON layer enum
# ("top" | "bottom" | "inner1" | "inner2" | ...). kerf's own reader maps the
# same KiCad layer to "top_copper" / "bottom_copper" / "inner_1" (see
# kicad_io._KICAD_TO_CJ_LAYER) — a deliberate, pre-existing naming
# convention (T-536 froze it), not something to reconcile here.
_KERF_LAYER_TO_ORACLE_LAYER = {
    "top_copper": "top",
    "bottom_copper": "bottom",
    "inner_1": "inner1",
    "inner_2": "inner2",
}

_EPS = 1e-6


def _strip_top_level_group(kicad_pcb_text: str) -> str:
    """Remove the top-level ``(group ...)`` node by paren-depth counting.

    kicad-to-circuit-json's underlying parser (`kicadts`) hard-crashes on
    this fixture's `(group "power_zone" (id UUID) (members ...))` node with
    `Class "id" not registered for parent "group"` — it only recognises
    `uuid` / `locked` / `members` as group children. But KiCad's own
    documented file format (https://dev-docs.kicad.org/en/file-formats/
    sexpr-intro/, "group" definition) is exactly
    `(group "NAME" (id UUID) (members UUID1 ... UUIDN))` — this fixture is
    spec-correct; kicadts has a real compliance gap, not us.

    `kicad_io.py`'s own reader is unaffected (see
    test_our_reader_survives_the_undocumented_group_field below): a `group`
    node is never modelled semantically, only carried in
    `kicad_passthrough`, so its exact children never get validated. Stripping
    it before handing the fixture to the oracle only works around the
    oracle's parser, and only for the oracle call — the un-stripped fixture
    is what `kicad_io.py` itself reads throughout this test.
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

    Hard failure, never a skip, if Node or the package is unavailable —
    see the module docstring and T-550's cautionary tale in tasks.md.
    """
    node = shutil.which("node")
    if node is None:
        raise RuntimeError(
            "T-526b conformance oracle requires Node.js on PATH (CI runs "
            "Node 22 — see .github/workflows/typecheck.yml). Not found: "
            "this is a hard test failure, not a skip."
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
            "T-526b conformance oracle (kicad-to-circuit-json) failed "
            f"(exit {proc.returncode}) — hard failure, not a skip. Is "
            "`kicad-to-circuit-json` installed (`npm ci` at repo root)? "
            f"stderr:\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


def _bbox(points: list) -> tuple:
    xs = [p["x"] for p in points]
    ys = [p["y"] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


class TestKicadOracleConformance(unittest.TestCase):
    """Compares kicad_io.py's reader against kicad-to-circuit-json over the
    same fixture, semantically (element type / layer / net / polygon
    bounding box / key numeric fields) rather than byte-for-byte — the two
    legitimately differ in id generation, key ordering, precision, and (see
    below) axis convention."""

    @classmethod
    def setUpClass(cls):
        cls.ours = kicad_pcb_to_circuit_json(_FIXTURE_TEXT)
        sanitized = _strip_top_level_group(_FIXTURE_TEXT)
        cls.oracle = _run_oracle_converter(sanitized)

    # ── the group-node compliance gap, pinned so this workaround is honest ──

    def test_oracle_chokes_on_kicads_own_documented_group_id_field(self):
        """Pins the exact upstream failure `_strip_top_level_group` works
        around, so the workaround gets deleted the day kicadts fixes it
        rather than lingering as an unverifiable comment."""
        with self.assertRaises(RuntimeError) as ctx:
            _run_oracle_converter(_FIXTURE_TEXT)
        self.assertIn('Class "id" not registered for parent "group"', str(ctx.exception))

    def test_our_reader_survives_the_undocumented_group_field(self):
        """Unlike the oracle, kicad_io.py never chokes on the group node:
        it isn't modelled, only carried verbatim in `kicad_passthrough`."""
        passthrough = next(e for e in self.ours if e["type"] == "kicad_passthrough")
        group_nodes = [n for n in passthrough["kicad_nodes"] if n[0] == "group"]
        self.assertEqual(len(group_nodes), 1)

    # ── net-bound copper pour: layer, net, and geometry agree ───────────────

    def test_net_bound_pour_layer_and_net_agree(self):
        ours = next(e for e in self.ours if e["type"] == "pcb_copper_pour")
        oracle_matches = [
            e for e in self.oracle
            if e["type"] == "pcb_copper_pour" and e.get("net_name")
        ]
        self.assertEqual(len(oracle_matches), 1)
        oracle = oracle_matches[0]

        self.assertEqual(oracle["net_name"], ours["net_id"])
        self.assertEqual(oracle["layer"], _KERF_LAYER_TO_ORACLE_LAYER[ours["layer"]])

    def test_net_bound_pour_geometry_agrees_within_declared_clearance(self):
        """kicad_io.py's `polygon` is the zone's *authored outline*
        (T-536's frozen field convention — needed downstream by fab/gerber
        and fab/odbpp, which recompute their own fill rather than trust
        KiCad's cached render). The oracle's `points` is the *filled*
        region taken from this fixture's `filled_polygon` cache, which is
        inset from the outline by the zone's own `connect_pads clearance`
        (0.2mm here). Both are legitimate, correct at their own level: the
        oracle's inset independently corroborates the clearance_mm kerf's
        reader extracted straight out of `connect_pads`."""
        ours = next(e for e in self.ours if e["type"] == "pcb_copper_pour")
        oracle = next(
            e for e in self.oracle
            if e["type"] == "pcb_copper_pour" and e.get("net_name")
        )

        our_bbox = _bbox(ours["polygon"])
        # T-538: kicad_io.py now applies the same KiCad Y-down -> Circuit
        # JSON Y-up flip the oracle applies (see
        # test_component_position_agrees_with_axis_convention below), so
        # both bounding boxes are already in the same (CJ Y-up) convention —
        # no manual un-flip needed here any more.
        oracle_bbox = _bbox(oracle["points"])

        clearance = ours["clearance_mm"]
        minx, miny, maxx, maxy = our_bbox
        ominx, ominy, omaxx, omaxy = oracle_bbox

        for inset in (ominx - minx, ominy - miny, maxx - omaxx, maxy - omaxy):
            self.assertGreaterEqual(inset, -_EPS)
            self.assertLessEqual(inset, clearance + _EPS)

    # ── no-net zone: ground_plane vs. copper_pour, a documented, deliberate
    #    divergence, not a bug ───────────────────────────────────────────────

    def test_no_net_zone_ground_plane_vs_copper_pour_is_a_deliberate_divergence(self):
        """kicad_io.py types a no-net zone as `pcb_ground_plane` (T-526,
        frozen by T-536's reconciliation). The oracle types *every* zone —
        net-bound or not — as `pcb_copper_pour` with an empty `net_name`,
        even though `pcb_ground_plane` is itself a real, distinct type in
        the official `circuit-json` schema (see
        node_modules/circuit-json/dist/index.d.mts). That makes kerf's
        distinction the more schema-faithful one, and it is the one the rest
        of Kerf (fab/gerber.py, fab/odbpp/writer.py, via_stitching.py — see
        test_t536_pour_reconciliation.py) is built against. Verdict: ours is
        right; this is not something to change.

        This fixture also exposes a hand-authoring gap the T-536/T-537 notes
        call out honestly: this zone has no `filled_polygon` cache (unlike
        the GND zone above), so the oracle's fallback is the raw outline —
        the two bounding boxes below match *exactly*, with no clearance
        inset, purely because this hand-authored fixture never populated a
        computed fill for this zone. A real pcbnew export would have one.
        """
        ours = next(e for e in self.ours if e["type"] == "pcb_ground_plane")
        oracle_matches = [
            e for e in self.oracle
            if e["type"] == "pcb_copper_pour" and not e.get("net_name")
        ]
        self.assertEqual(len(oracle_matches), 1)
        oracle = oracle_matches[0]

        self.assertEqual(oracle["layer"], _KERF_LAYER_TO_ORACLE_LAYER[ours["layer"]])

        # T-538: both sides are now in the same (CJ Y-up) convention.
        our_bbox = _bbox(ours["polygon"])
        oracle_bbox = _bbox(oracle["points"])
        for a, b in zip(our_bbox, oracle_bbox):
            self.assertAlmostEqual(a, b, places=6)

    # ── keepout: a real scope gap in the oracle, not a defect in ours ──────

    def test_keepout_zone_is_invisible_to_the_oracle(self):
        """`pcb_keepout` is a real type in the official circuit-json schema
        (node_modules/circuit-json/dist/index.d.mts), but
        kicad-to-circuit-json's `CollectZonesStage` only emits
        `pcb_copper_pour` — it never converts a KiCad `keepout` zone at all.
        Verdict: this is a scope gap in the independent tool, not evidence
        against kerf's reader, which does model keepouts (T-526)."""
        ours_keepout = next(e for e in self.ours if e["type"] == "pcb_keepout")
        self.assertIsNotNone(ours_keepout)

        oracle_types = {e["type"] for e in self.oracle}
        self.assertNotIn("pcb_keepout", oracle_types)

        # Nothing else in the oracle output claims the keepout's own polygon
        # region either — it's dropped outright, not re-typed. (T-538: both
        # sides are now in the same CJ Y-up convention.)
        keepout_bbox = _bbox(ours_keepout["polygon"])
        for e in self.oracle:
            if e["type"] == "pcb_copper_pour":
                other_bbox = _bbox(e["points"])
                self.assertNotEqual(other_bbox, keepout_bbox)

    # ── gr_text off silk/fab layers: a real scope gap in the oracle ────────

    def test_gr_text_off_silk_fab_layers_is_invisible_to_the_oracle(self):
        """kicad_io.py recovers every free-floating `gr_text` as `pcb_text`
        regardless of layer (T-526). The oracle's `CollectGraphicsStage`
        only handles `gr_text` "on silk/fab layers" by its own doc comment
        (node_modules/kicad-to-circuit-json/dist/index.d.ts) — this
        fixture's "REV A" sits on `Cmts.User`, so the oracle drops it.
        Verdict: another scope gap in the independent tool; kerf's reader is
        more complete here, not wrong."""
        ours_text = next(e for e in self.ours if e["type"] == "pcb_text")
        self.assertEqual(ours_text["text"], "REV A")

        oracle_texts = {e.get("text") for e in self.oracle if "text" in e}
        self.assertNotIn("REV A", oracle_texts)

    # ── coordinate convention: T-538, fixed — straight equality now ────────

    def test_component_position_agrees_with_axis_convention(self):
        """T-538 (was test_component_position_agrees_modulo_y_axis_convention):
        this used to be a pinned, documented DIVERGENCE — the oracle applies
        the KiCad(Y-down) -> Circuit JSON(Y-up) axis flip
        (node_modules/kicad-to-circuit-json/dist/index.js,
        InitializePcbContextStage: `compose(scale(1, -1), translate(-center.x,
        -center.y))`) and kicad_io.py did not flip Y anywhere in the module.

        `kicad_io.py` now applies that flip too (see
        `_flip_kicad_y_to_circuit_json_y` in kicad_io.py for the axis
        rationale — a fixed origin, `cj_y = -kicad_y`, not the oracle's
        board-bounding-box recentering, which this fixture's lack of an
        Edge.Cuts outline degenerates to `{0, 0}` anyway). The two now agree
        exactly, with no modulo/flip-back needed in this assertion — this is
        a straight equality check, not equality-modulo-convention.
        """
        ours = next(e for e in self.ours if e["type"] == "pcb_component")
        oracle = next(e for e in self.oracle if e["type"] == "pcb_component")

        self.assertAlmostEqual(oracle["center"]["x"], ours["x"], places=6)
        self.assertAlmostEqual(oracle["center"]["y"], ours["y"], places=6)


if __name__ == "__main__":
    unittest.main()
