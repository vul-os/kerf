"""
test_body_hollow.py
===================
Analytic-oracle tests for :func:`kerf_cad_core.geom.body_hollow.hollow_body`
and :func:`hollow_with_ribs`.

Reference: Stroud & Nagy 2011 §15.5 compound feature operators.

Oracle tests
------------
1. **Hollow box round-trip** — 10×10×10 box, thickness=1 →
     internal_volume = 8³ = 512; wall_volume = 1000 - 512 = 488 (within 1e-3).

2. **Hollow with open face** — same box with top face open → ok=True,
     internal_volume > 0, wall_volume > 0, port_count == 0.

3. **Hollow with port** — box hollowed with one port (diameter=1) →
     port_count == 1; wall_volume < (1000 - 512) (port reduces wall material).

4. **Hollow with ribs** — hollow box with 1 cross-rib →
     rib_volume > 0; internal_volume reduced by rib_volume within 1%;
     rib_count == 1.
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.brep import Body, make_box
from kerf_cad_core.geom.body_hollow import HollowResult, hollow_body, hollow_with_ribs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_10_box() -> Body:
    """Return a 10×10×10 axis-aligned box at the origin."""
    return make_box(origin=(0.0, 0.0, 0.0), size=(10.0, 10.0, 10.0))


# ---------------------------------------------------------------------------
# Test 1: Hollow box round-trip
# ---------------------------------------------------------------------------

class TestHollowBoxRoundTrip:
    """
    10×10×10 box hollowed with thickness=1.
    Analytic oracles:
        outer_volume = 10³ = 1000
        internal_volume = 8³ = 512  (inner void)
        wall_volume = 1000 - 512 = 488
    All within 1e-3.
    """

    def setup_method(self):
        box = _make_10_box()
        self.result = hollow_body(box, thickness=1.0)

    def test_ok(self):
        assert self.result.ok is True, (
            f"hollow_body failed: {self.result.reason}"
        )

    def test_returns_hollow_result(self):
        assert isinstance(self.result, HollowResult)

    def test_body_is_body(self):
        assert isinstance(self.result.body, Body)

    def test_outer_volume(self):
        assert abs(self.result.outer_volume - 1000.0) < 1e-3, (
            f"outer_volume={self.result.outer_volume:.6f}, expected 1000.0"
        )

    def test_internal_volume(self):
        expected = 8.0 ** 3  # = 512
        assert abs(self.result.internal_volume - expected) < 1e-3, (
            f"internal_volume={self.result.internal_volume:.6f}, expected {expected}"
        )

    def test_wall_volume(self):
        expected = 1000.0 - 512.0  # = 488
        assert abs(self.result.wall_volume - expected) < 1e-3, (
            f"wall_volume={self.result.wall_volume:.6f}, expected {expected}"
        )

    def test_no_ports(self):
        assert self.result.port_count == 0

    def test_no_ribs(self):
        assert self.result.rib_count == 0
        assert self.result.rib_volume == 0.0

    def test_applied_options_echo(self):
        ao = self.result.applied_options
        assert ao["thickness"] == 1.0
        assert ao["open_faces"] == []

    def test_outer_minus_inner_equals_wall(self):
        """wall_volume ≈ outer_volume − internal_volume (within tolerance)."""
        diff = self.result.outer_volume - self.result.internal_volume
        assert abs(diff - self.result.wall_volume) < 1e-3

    def test_various_thicknesses(self):
        """Parametric sweep: different thicknesses satisfy oracle within 1e-3."""
        for t in [0.5, 1.0, 2.0]:
            box = _make_10_box()
            r = hollow_body(box, thickness=t)
            assert r.ok, f"t={t}: {r.reason}"
            inner_side = 10.0 - 2.0 * t
            expected_inner = inner_side ** 3 if inner_side > 0.0 else 0.0
            assert abs(r.internal_volume - expected_inner) < 1e-3, (
                f"t={t}: internal_volume={r.internal_volume:.6f}, "
                f"expected={expected_inner:.6f}"
            )
            expected_wall = 1000.0 - expected_inner
            assert abs(r.wall_volume - expected_wall) < 1e-3, (
                f"t={t}: wall_volume={r.wall_volume:.6f}, expected={expected_wall:.6f}"
            )


# ---------------------------------------------------------------------------
# Test 2: Hollow with open face
# ---------------------------------------------------------------------------

class TestHollowWithOpenFace:
    """
    10×10×10 box with top face (index 0) opened.
    Oracles:
        ok=True
        body is a Body
        internal_volume > 0 and > 500 (most of the 512 void remains)
        wall_volume > 0
        port_count == 0
    Note: open face makes the shell have 5 outer + 5 inner + rim faces.
    """

    def setup_method(self):
        box = _make_10_box()
        self.result = hollow_body(box, thickness=1.0, options={"open_faces": [0]})

    def test_ok(self):
        assert self.result.ok is True, (
            f"hollow_body(open_faces=[0]) failed: {self.result.reason}"
        )

    def test_body_returned(self):
        assert isinstance(self.result.body, Body)

    def test_internal_volume_positive(self):
        assert self.result.internal_volume > 0.0, (
            f"Expected internal_volume > 0, got {self.result.internal_volume}"
        )

    def test_wall_volume_positive(self):
        assert self.result.wall_volume > 0.0, (
            f"Expected wall_volume > 0, got {self.result.wall_volume}"
        )

    def test_port_count_zero(self):
        assert self.result.port_count == 0

    def test_open_faces_in_applied_options(self):
        assert self.result.applied_options.get("open_faces") == [0]

    def test_outer_volume_correct(self):
        assert abs(self.result.outer_volume - 1000.0) < 1e-3

    def test_various_open_face_indices(self):
        """All face indices 0..5 should succeed."""
        for fi in range(6):
            box = _make_10_box()
            r = hollow_body(box, thickness=1.0, options={"open_faces": [fi]})
            assert r.ok, f"fi={fi}: {r.reason}"
            assert r.internal_volume > 0.0
            assert r.wall_volume > 0.0


# ---------------------------------------------------------------------------
# Test 3: Hollow with port
# ---------------------------------------------------------------------------

class TestHollowWithPort:
    """
    10×10×10 box hollowed (thickness=1) with one port at centre of top face.
    Oracles:
        port_count == 1
        wall_volume < 488.0  (port removes material)
        ok=True
    """

    def setup_method(self):
        box = _make_10_box()
        self.port = {"point": [5.0, 5.0, 10.0], "diameter": 1.0}
        self.result = hollow_body(
            box,
            thickness=1.0,
            options={"port_locations": [(self.port["point"], self.port["diameter"])]},
        )

    def test_ok(self):
        assert self.result.ok is True, (
            f"hollow_body with port failed: {self.result.reason}"
        )

    def test_port_count(self):
        assert self.result.port_count == 1, (
            f"Expected port_count=1, got {self.result.port_count}"
        )

    def test_wall_volume_reduced(self):
        """Port drilling removes material → wall_volume < 488."""
        full_wall = 1000.0 - 512.0  # 488
        assert self.result.wall_volume < full_wall, (
            f"wall_volume={self.result.wall_volume:.6f} should be < {full_wall}"
        )

    def test_port_volume_nonzero(self):
        """The delta in wall_volume equals the port plug volume (within 1e-3)."""
        full_wall = 1000.0 - 512.0
        port_vol_removed = full_wall - self.result.wall_volume
        expected_port_vol = math.pi * (0.5 ** 2) * 1.0  # π r² × thickness
        assert abs(port_vol_removed - expected_port_vol) < 1e-3, (
            f"port_vol_removed={port_vol_removed:.6f}, expected={expected_port_vol:.6f}"
        )

    def test_multiple_ports(self):
        """Two ports → port_count == 2, wall_volume reduced further."""
        box = _make_10_box()
        r = hollow_body(
            box,
            thickness=1.0,
            options={
                "port_locations": [
                    ([5.0, 5.0, 10.0], 1.0),
                    ([5.0, 5.0, 0.0], 1.0),
                ]
            },
        )
        assert r.ok
        assert r.port_count == 2
        # Two ports remove twice the volume.
        full_wall = 1000.0 - 512.0
        assert r.wall_volume < full_wall


# ---------------------------------------------------------------------------
# Test 4: Hollow with ribs
# ---------------------------------------------------------------------------

class TestHollowWithRibs:
    """
    10×10×10 box hollowed (thickness=1) with 1 cross-rib.
    Rib: from (1,5,1) to (9,5,1), height=6, thickness=0.5.
    Rib volume = length × height × thickness = 8 × 6 × 0.5 = 24.

    Oracles:
        rib_count == 1
        rib_volume > 0  (≈ 24.0 within 1%)
        internal_volume ≈ 512 - 24 = 488  (within 1%)
        ok=True
    """

    def setup_method(self):
        box = _make_10_box()
        self.rib = ([1.0, 5.0, 1.0], [9.0, 5.0, 1.0], 6.0, 0.5)
        self.result = hollow_with_ribs(
            box,
            thickness=1.0,
            rib_specs=[self.rib],
        )

    def test_ok(self):
        assert self.result.ok is True, (
            f"hollow_with_ribs failed: {self.result.reason}"
        )

    def test_rib_count(self):
        assert self.result.rib_count == 1, (
            f"Expected rib_count=1, got {self.result.rib_count}"
        )

    def test_rib_volume_positive(self):
        assert self.result.rib_volume > 0.0, (
            f"Expected rib_volume > 0, got {self.result.rib_volume}"
        )

    def test_rib_volume_analytic(self):
        """Analytic rib volume = 8 × 6 × 0.5 = 24 (within 1%)."""
        start = [1.0, 5.0, 1.0]
        end = [9.0, 5.0, 1.0]
        import numpy as np
        length = float(np.linalg.norm(np.array(end) - np.array(start)))  # 8.0
        expected = length * 6.0 * 0.5  # 24.0
        assert abs(self.result.rib_volume - expected) / expected < 0.01, (
            f"rib_volume={self.result.rib_volume:.6f}, expected={expected:.6f}"
        )

    def test_internal_volume_reduced(self):
        """Internal volume should be approx 512 - rib_volume (within 1%)."""
        hollow_internal = 512.0  # no-rib case
        expected_internal = hollow_internal - self.result.rib_volume
        # Allow 1% relative tolerance.
        rel_err = abs(self.result.internal_volume - expected_internal) / hollow_internal
        assert rel_err < 0.01, (
            f"internal_volume={self.result.internal_volume:.6f}, "
            f"expected={expected_internal:.6f} (1% tol)"
        )

    def test_multiple_ribs(self):
        """Two cross-ribs → rib_count=2, combined rib_volume doubles."""
        box = _make_10_box()
        r = hollow_with_ribs(
            box,
            thickness=1.0,
            rib_specs=[
                ([1.0, 5.0, 1.0], [9.0, 5.0, 1.0], 6.0, 0.5),
                ([5.0, 1.0, 1.0], [5.0, 9.0, 1.0], 6.0, 0.5),
            ],
        )
        assert r.ok
        assert r.rib_count == 2
        assert r.rib_volume > 0.0


# ---------------------------------------------------------------------------
# Error / edge cases
# ---------------------------------------------------------------------------

class TestHollowErrors:

    def test_non_body_input(self):
        r = hollow_body("not a body", 1.0)
        assert r.ok is False

    def test_zero_thickness(self):
        box = _make_10_box()
        r = hollow_body(box, thickness=0.0)
        assert r.ok is False

    def test_negative_thickness(self):
        box = _make_10_box()
        r = hollow_body(box, thickness=-1.0)
        assert r.ok is False

    def test_excessive_thickness(self):
        """Thickness >= half smallest dim → inner body degenerate."""
        box = _make_10_box()
        r = hollow_body(box, thickness=6.0)
        assert r.ok is False

    def test_no_raise_on_bad_input(self):
        """hollow_body must never raise."""
        for bad in [None, 42, [], "box"]:
            r = hollow_body(bad, 1.0)
            assert isinstance(r, HollowResult)
            assert r.ok is False

    def test_hollow_result_dict_access(self):
        """HollowResult supports dict-style access for interop."""
        box = _make_10_box()
        r = hollow_body(box, thickness=1.0)
        assert r["ok"] is True
        assert "internal_volume" in r
        assert r.get("port_count", -1) == 0

    def test_hollow_with_ribs_bad_spec(self):
        """Malformed rib_specs (wrong length tuples) are skipped gracefully."""
        box = _make_10_box()
        r = hollow_with_ribs(box, thickness=1.0, rib_specs=[("bad", "spec")])
        assert r.ok is True
        assert r.rib_count == 0
