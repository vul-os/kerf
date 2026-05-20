"""
GK-45: test_shell_hollow.py
===========================
Tests for :func:`kerf_cad_core.geom.solid_features.shell_body`.

Oracle assertions
-----------------
- Shelled box wall thickness = t exact (inner vertex distance from outer = t).
- Both inner and outer shells individually satisfy ``validate_body``.
- hollow volume = outer_volume − inner_volume (to ≤ 1e-6).
- Open-shell body: rim faces formed, outer loop edge becomes aperture.
- Bad inputs return ok=False without raising.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Body,
    Face,
    Shell,
    Solid,
    Vertex,
    make_box,
    validate_body,
)
from kerf_cad_core.geom.solid_features import shell_body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _box_volumes(w: float, d: float, h: float, t: float):
    """Analytical outer and inner volumes for a box shell."""
    v_outer = w * d * h
    iw, id_, ih = w - 2 * t, d - 2 * t, h - 2 * t
    v_inner = max(0.0, iw) * max(0.0, id_) * max(0.0, ih)
    return v_outer, v_inner


# ---------------------------------------------------------------------------
# Basic closed shell (no open face)
# ---------------------------------------------------------------------------

class TestShellBodyClosed:

    def _run(self, w=4.0, d=3.0, h=2.0, t=0.5, origin=(0.0, 0.0, 0.0)):
        box = make_box(origin=origin, size=(w, d, h))
        return shell_body(box, t)

    # --- ok / structure -------------------------------------------------------

    def test_ok_returns_true(self):
        r = self._run()
        assert r["ok"] is True, r.get("reason", "")

    def test_body_is_returned(self):
        r = self._run()
        assert isinstance(r["body"], Body)

    def test_open_face_index_is_none(self):
        r = self._run()
        assert r["open_face_index"] is None

    def test_wall_thickness_reported(self):
        r = self._run(t=0.3)
        assert abs(r["wall_thickness"] - 0.3) < 1e-12

    # --- topology / validity --------------------------------------------------

    def test_outer_shell_validates(self):
        """The outer shell alone must pass validate_body."""
        r = self._run()
        assert r["ok"] is True
        new_body = r["body"]
        # The outer shell is shells[0] of the solid; wrap it in a standalone body
        outer_shell = new_body.solids[0].shells[0]
        standalone = Body(solids=[Solid([outer_shell])])
        res = validate_body(standalone)
        assert res["ok"] is True, res["errors"]

    def test_inner_shell_validates(self):
        """The inner shell alone must pass validate_body."""
        r = self._run()
        assert r["ok"] is True
        new_body = r["body"]
        inner_shell = new_body.solids[0].shells[1]
        standalone = Body(solids=[Solid([inner_shell])])
        res = validate_body(standalone)
        assert res["ok"] is True, res["errors"]

    def test_full_body_validates(self):
        """The full hollow body must pass validate_body."""
        r = self._run()
        assert r["ok"] is True
        res = validate_body(r["body"])
        assert res["ok"] is True, res["errors"]

    def test_solid_has_two_shells(self):
        """Hollow body solid must have exactly 2 shells (outer + inner void)."""
        r = self._run()
        assert r["ok"] is True
        solid = r["body"].solids[0]
        assert len(solid.shells) == 2

    def test_both_shells_closed(self):
        """Both shells must be is_closed=True."""
        r = self._run()
        solid = r["body"].solids[0]
        for sh in solid.shells:
            assert sh.is_closed is True

    def test_outer_shell_has_six_faces(self):
        """Outer shell of a shelled box still has 6 faces."""
        r = self._run()
        outer_shell = r["body"].solids[0].shells[0]
        assert len(outer_shell.faces) == 6

    def test_inner_shell_has_six_faces(self):
        """Inner shell of a shelled box also has 6 faces."""
        r = self._run()
        inner_shell = r["body"].solids[0].shells[1]
        assert len(inner_shell.faces) == 6

    # --- oracle: wall thickness exact -----------------------------------------

    def test_wall_thickness_exact_unit_box(self):
        """
        For a unit box (1×1×1) shelled with t=0.1, every inner vertex must be
        exactly 0.1 units away from the nearest outer face's plane.
        """
        t = 0.1
        box = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
        r = shell_body(box, t)
        assert r["ok"] is True
        inner_shell = r["body"].solids[0].shells[1]
        inner_verts = inner_shell.vertices()
        for v in inner_verts:
            x, y, z = v.point
            # Each inner vertex should be t away from all 3 incident outer planes.
            # For a unit box at origin: outer faces at x=0,1; y=0,1; z=0,1.
            # Inner vertices should be at x=t or x=1-t, etc.
            dists = [
                abs(x - t),
                abs(x - (1.0 - t)),
                abs(y - t),
                abs(y - (1.0 - t)),
                abs(z - t),
                abs(z - (1.0 - t)),
            ]
            assert min(dists) < 1e-8, (
                f"Inner vertex {v.point} not at distance t={t} from outer face plane. "
                f"min dist to inner plane = {min(dists)}"
            )

    def test_wall_thickness_exact_asymmetric_box(self):
        """Wall thickness t=0.25 on a 5×3×2 box — inner vertex check."""
        t = 0.25
        ox, oy, oz = 1.0, 2.0, -1.0
        box = make_box(origin=(ox, oy, oz), size=(5.0, 3.0, 2.0))
        r = shell_body(box, t)
        assert r["ok"] is True
        inner_shell = r["body"].solids[0].shells[1]
        for v in inner_shell.vertices():
            x, y, z = v.point
            dists_to_inner_planes = [
                abs(x - (ox + t)),
                abs(x - (ox + 5.0 - t)),
                abs(y - (oy + t)),
                abs(y - (oy + 3.0 - t)),
                abs(z - (oz + t)),
                abs(z - (oz + 2.0 - t)),
            ]
            assert min(dists_to_inner_planes) < 1e-8, (
                f"Inner vertex {v.point} not on an inner face plane (t={t})"
            )

    def test_wall_thickness_multiple_values(self):
        """Test several wall thicknesses on the same base box."""
        for t in (0.1, 0.2, 0.4):
            box = make_box(size=(3.0, 3.0, 3.0))
            r = shell_body(box, t)
            assert r["ok"] is True, f"t={t}: {r.get('reason')}"
            inner_shell = r["body"].solids[0].shells[1]
            for v in inner_shell.vertices():
                x, y, z = v.point
                dists = [
                    abs(x - t), abs(x - (3.0 - t)),
                    abs(y - t), abs(y - (3.0 - t)),
                    abs(z - t), abs(z - (3.0 - t)),
                ]
                assert min(dists) < 1e-8, f"t={t}, vertex {v.point}"

    # --- oracle: volume = outer - inner ----------------------------------------

    def test_hollow_volume_equals_outer_minus_inner(self):
        """hollow volume ≡ outer_volume − inner_volume (≤ 1e-6 tol)."""
        w, d, h, t = 4.0, 3.0, 2.0, 0.5
        r = shell_body(make_box(size=(w, d, h)), t)
        assert r["ok"] is True
        v_outer_expected, v_inner_expected = _box_volumes(w, d, h, t)
        assert abs(r["volume_outer"] - v_outer_expected) < 1e-6, (
            f"volume_outer={r['volume_outer']} != expected {v_outer_expected}"
        )
        assert abs(r["volume_inner"] - v_inner_expected) < 1e-6, (
            f"volume_inner={r['volume_inner']} != expected {v_inner_expected}"
        )
        hollow_vol = r["volume_outer"] - r["volume_inner"]
        expected_hollow = v_outer_expected - v_inner_expected
        assert abs(hollow_vol - expected_hollow) < 1e-6

    def test_hollow_volume_small_thickness(self):
        """Very small t → inner volume close to outer."""
        w, d, h, t = 10.0, 10.0, 10.0, 0.01
        r = shell_body(make_box(size=(w, d, h)), t)
        assert r["ok"] is True
        v_outer, v_inner = _box_volumes(w, d, h, t)
        assert abs(r["volume_outer"] - v_outer) < 1e-6
        assert abs(r["volume_inner"] - v_inner) < 1e-6

    def test_hollow_volume_larger_thickness(self):
        """Moderate t — hollow volume test."""
        w, d, h, t = 6.0, 4.0, 3.0, 0.8
        r = shell_body(make_box(size=(w, d, h)), t)
        assert r["ok"] is True
        v_outer, v_inner = _box_volumes(w, d, h, t)
        assert abs(r["volume_outer"] - v_outer) < 1e-6
        assert abs(r["volume_inner"] - v_inner) < 1e-6

    def test_volume_relationship_consistency(self):
        """volume_outer > volume_inner for all feasible inputs."""
        for w, d, h, t in [(5, 4, 3, 0.5), (2, 2, 2, 0.3), (10, 8, 6, 1.0)]:
            r = shell_body(make_box(size=(w, d, h)), t)
            assert r["ok"] is True
            assert r["volume_outer"] > r["volume_inner"]

    # --- face / edge / vertex counts ------------------------------------------

    def test_topology_counts_box(self):
        """Shelled box: 12 faces total (6 outer + 6 inner), 24 edges each shell."""
        r = self._run()
        assert r["ok"] is True
        assert r["n_faces"] == 12  # 6 outer + 6 inner


# ---------------------------------------------------------------------------
# Open shell (one face removed)
# ---------------------------------------------------------------------------

class TestShellBodyOpen:

    def _run(self, w=4.0, d=3.0, h=2.0, t=0.3, fi=0):
        box = make_box(size=(w, d, h))
        return shell_body(box, t, open_face_index=fi)

    def test_ok_returns_true(self):
        r = self._run()
        assert r["ok"] is True, r.get("reason", "")

    def test_open_face_index_reported(self):
        r = self._run(fi=1)
        assert r["open_face_index"] == 1

    def test_body_returned(self):
        r = self._run()
        assert isinstance(r["body"], Body)

    def test_outer_minus_one_face(self):
        """Outer faces of an open-shell body = 5 (one removed)."""
        r = self._run(fi=0)
        assert r["ok"] is True
        # Single open shell in the solid
        all_faces = r["body"].all_faces()
        # 5 outer + 5 inner + 4 rim faces = 14
        assert len(all_faces) == 14, f"Expected 14 faces, got {len(all_faces)}"

    def test_all_face_indices_valid(self):
        """open_face_index 0..5 all succeed for a box."""
        for fi in range(6):
            box = make_box(size=(4.0, 3.0, 2.0))
            r = shell_body(box, 0.3, open_face_index=fi)
            assert r["ok"] is True, f"fi={fi}: {r.get('reason')}"

    def test_rim_faces_count(self):
        """Open shell has 4 rim faces (one quad per removed face edge)."""
        r = self._run()
        gp = r["geometry_params"]
        assert gp["n_rim_faces"] == 4

    def test_volume_reported(self):
        """volume_outer and volume_inner are positive."""
        r = self._run()
        assert r["volume_outer"] > 0
        assert r["volume_inner"] > 0

    def test_open_shell_body_has_one_solid(self):
        """Open-shell body still has exactly one solid."""
        r = self._run()
        assert r["ok"] is True
        assert len(r["body"].solids) == 1


# ---------------------------------------------------------------------------
# Error / edge cases
# ---------------------------------------------------------------------------

class TestShellBodyErrors:

    def test_non_body_input_returns_ok_false(self):
        r = shell_body("not a body", 0.5)
        assert r["ok"] is False

    def test_zero_thickness_returns_ok_false(self):
        box = make_box()
        r = shell_body(box, 0.0)
        assert r["ok"] is False

    def test_negative_thickness_returns_ok_false(self):
        box = make_box()
        r = shell_body(box, -1.0)
        assert r["ok"] is False

    def test_excessive_thickness_returns_ok_false(self):
        """t >= half the smallest dimension → degenerate inner body."""
        box = make_box(size=(1.0, 1.0, 1.0))
        r = shell_body(box, 0.6)  # 2*0.6 = 1.2 > 1.0 → inner size < 0
        assert r["ok"] is False

    def test_open_face_index_out_of_range_returns_ok_false(self):
        box = make_box()
        r = shell_body(box, 0.1, open_face_index=10)
        assert r["ok"] is False

    def test_open_face_index_negative_returns_ok_false(self):
        box = make_box()
        r = shell_body(box, 0.1, open_face_index=-1)
        assert r["ok"] is False

    def test_no_raise_on_bad_input(self):
        """shell_body must never raise; always return a dict."""
        for arg in [None, 42, [], "box"]:
            r = shell_body(arg, 0.5)
            assert isinstance(r, dict)
            assert "ok" in r

    def test_empty_body_returns_ok_false(self):
        """Body with no solids → ok=False."""
        empty = Body()
        r = shell_body(empty, 0.3)
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# Oracle parametric sweep
# ---------------------------------------------------------------------------

class TestOracleParametricSweep:
    """Parametric sweep asserting the three oracle properties simultaneously."""

    @pytest.mark.parametrize("w,d,h,t", [
        (4.0, 4.0, 4.0, 0.5),
        (6.0, 3.0, 2.0, 0.4),
        (5.0, 5.0, 5.0, 1.0),
        (8.0, 6.0, 4.0, 0.8),
        (3.0, 2.0, 1.5, 0.2),
    ])
    def test_oracle_triple(self, w, d, h, t):
        """
        Oracle: (1) wall thickness exact; (2) inner+outer validate_body ok;
                (3) hollow volume = outer - inner ≤ 1e-6.
        """
        box = make_box(size=(w, d, h))
        r = shell_body(box, t)
        assert r["ok"] is True, f"w={w} d={d} h={h} t={t}: {r.get('reason')}"

        new_body = r["body"]

        # (1) validate_body on inner and outer shells independently
        solid = new_body.solids[0]
        for shi, sh in enumerate(solid.shells):
            standalone = Body(solids=[Solid([sh])])
            res = validate_body(standalone)
            assert res["ok"] is True, (
                f"shell {shi} invalid for w={w} d={d} h={h} t={t}: {res['errors']}"
            )

        # (2) Wall thickness exact: all inner vertices lie on inner face planes
        inner_shell = solid.shells[1]
        for v in inner_shell.vertices():
            x, y, z = v.point
            dists = [
                abs(x - t), abs(x - (w - t)),
                abs(y - t), abs(y - (d - t)),
                abs(z - t), abs(z - (h - t)),
            ]
            assert min(dists) < 1e-7, (
                f"Inner vertex {v.point} not at distance t={t} from outer face "
                f"(w={w} d={d} h={h})"
            )

        # (3) Hollow volume
        v_outer_exp, v_inner_exp = _box_volumes(w, d, h, t)
        assert abs(r["volume_outer"] - v_outer_exp) < 1e-6, (
            f"volume_outer={r['volume_outer']:.8f} vs expected={v_outer_exp:.8f}"
        )
        assert abs(r["volume_inner"] - v_inner_exp) < 1e-6, (
            f"volume_inner={r['volume_inner']:.8f} vs expected={v_inner_exp:.8f}"
        )
        hollow_vol = r["volume_outer"] - r["volume_inner"]
        expected_hollow = v_outer_exp - v_inner_exp
        assert abs(hollow_vol - expected_hollow) < 1e-6, (
            f"hollow volume mismatch: got {hollow_vol:.8f} expected {expected_hollow:.8f}"
        )
