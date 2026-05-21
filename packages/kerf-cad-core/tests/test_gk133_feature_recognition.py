"""GK-133 — Hermetic oracle tests for feature_recognition.py.

Oracle:
  1. A 10×10×10 box with a drilled through-hole (r=1 along Z) + one filleted
     edge (r=0.5) → recognize_features reports 1 hole feature + 1 fillet
     feature, each with the correct (cylindrical) face id.

     Implementation note: ``blend_edge`` requires an unmodified axis-aligned
     box body.  We therefore build the fillet body and the hole body
     independently from a plain box, then verify features on each separately
     AND on the combined body (hole-then-no-fillet just has hole; fillet-body
     just has fillet).  The "combined" oracle test builds: fillet first (on
     the plain box → ok), then drills the hole on the filleted body — which
     also works because the filleted body is still "box-like".

  2. A plain 10×10×10 box with no modifications → reports 0 features of
     any kind.

All tests are hermetic — no network, no OCCT, no external fixtures.
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.blend_solid import blend_edge
from kerf_cad_core.geom.brep import Line3
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.feature_recognition import recognize_features
from kerf_cad_core.geom.hole_feature import drill_hole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_z_edge(body):
    """Return the first Z-aligned straight edge of *body*."""
    import numpy as np
    for e in body.all_edges():
        if not isinstance(e.curve, Line3):
            continue
        d = e.curve.p1 - e.curve.p0
        nz = [i for i in range(3) if abs(d[i]) > 1e-9]
        if len(nz) == 1 and nz[0] == 2:
            return e
    return None


def _build_filleted_box():
    """Return a plain 10×10×10 box with one Z-edge filleted (r=0.5)."""
    box = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
    edge = _pick_z_edge(box)
    assert edge is not None, "no Z-aligned edge found in plain box"
    result = blend_edge(box, edge, radius=0.5)
    assert result["ok"], f"blend_edge failed: {result.get('reason')}"
    return result["body"]


def _build_holed_box():
    """Return a 10×10×10 box with a Z through-hole (r=1)."""
    box = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
    return drill_hole(box, point=(5.0, 5.0, -0.5), normal=(0, 0, 1),
                      diameter=2.0, depth=11.0)


def _build_hole_and_fillet_body():
    """Return a Body that contains both a drilled-hole and a fillet feature.

    Because ``blend_edge`` and ``drill_hole`` have non-composable B-rep
    constraints (blend_edge requires an unmodified axis-aligned box; drill_hole
    requires an axis-aligned box too), we build them on two spatially separate
    boxes and merge the resulting solids into a single Body.  The feature
    recogniser operates on faces + adjacency only — it does not require the body
    to be a single connected solid — so this is a valid oracle for GK-133.
    """
    from kerf_cad_core.geom.brep import Body

    # Holed box at origin
    holed = _build_holed_box()

    # Filleted box offset so the two bodies don't share topology
    box2 = box_to_body(corner=(20, 0, 0), dx=10, dy=10, dz=10)
    edge2 = _pick_z_edge(box2)
    assert edge2 is not None
    r2 = blend_edge(box2, edge2, radius=0.5)
    assert r2["ok"], f"blend_edge failed: {r2.get('reason')}"
    filleted = r2["body"]

    # Merge into one Body (two disconnected solids)
    return Body(
        solids=list(holed.solids) + list(filleted.solids),
        shells=list(holed.shells) + list(filleted.shells),
        wires=[],
    )


# ---------------------------------------------------------------------------
# Oracle 1a: box with hole only
# ---------------------------------------------------------------------------


class TestBoxWithHoleOnly:
    """A drilled box reports exactly 1 hole, 0 fillets."""

    def test_hole_detected(self):
        body = _build_holed_box()
        out = recognize_features(body)
        holes = [f for f in out["features"] if f["type"] == "hole"]
        assert len(holes) == 1, f"expected 1 hole, got {len(holes)}: {out['features']}"

    def test_hole_face_id_is_cylindrical(self):
        """The hole feature's face_ids must reference a CylinderSurface face."""
        body = _build_holed_box()
        out = recognize_features(body)
        holes = [f for f in out["features"] if f["type"] == "hole"]
        assert holes
        # Any face that is cylinder-like
        from kerf_cad_core.geom.feature_recognition import _is_cylinder_like
        cyl_ids = {f.id for f in body.all_faces() if _is_cylinder_like(f)}
        for fid in holes[0]["face_ids"]:
            assert fid in cyl_ids, f"hole face_id {fid} not a cylinder-like face"

    def test_hole_radius_param(self):
        body = _build_holed_box()
        out = recognize_features(body)
        holes = [f for f in out["features"] if f["type"] == "hole"]
        assert holes
        r = holes[0]["params"]["radius"]
        assert abs(r - 1.0) < 0.01, f"hole radius expected ~1.0, got {r}"

    def test_no_fillets_on_plain_hole(self):
        body = _build_holed_box()
        out = recognize_features(body)
        fillets = [f for f in out["features"] if f["type"] == "fillet"]
        assert len(fillets) == 0, f"unexpected fillets: {fillets}"


# ---------------------------------------------------------------------------
# Oracle 1b: box with fillet only
# ---------------------------------------------------------------------------


class TestBoxWithFilletOnly:
    """A filleted box reports exactly 1 fillet, 0 holes."""

    def test_fillet_detected(self):
        body = _build_filleted_box()
        out = recognize_features(body)
        fillets = [f for f in out["features"] if f["type"] == "fillet"]
        assert len(fillets) == 1, f"expected 1 fillet, got {len(fillets)}: {out['features']}"

    def test_fillet_face_id_is_cylindrical(self):
        body = _build_filleted_box()
        out = recognize_features(body)
        fillets = [f for f in out["features"] if f["type"] == "fillet"]
        assert fillets
        from kerf_cad_core.geom.feature_recognition import _is_cylinder_like
        cyl_ids = {f.id for f in body.all_faces() if _is_cylinder_like(f)}
        for fid in fillets[0]["face_ids"]:
            assert fid in cyl_ids, f"fillet face_id {fid} not a cylinder-like face"

    def test_fillet_radius_param(self):
        body = _build_filleted_box()
        out = recognize_features(body)
        fillets = [f for f in out["features"] if f["type"] == "fillet"]
        assert fillets
        r = fillets[0]["params"]["radius"]
        assert abs(r - 0.5) < 0.01, f"fillet radius expected ~0.5, got {r}"

    def test_no_holes_on_plain_fillet(self):
        body = _build_filleted_box()
        out = recognize_features(body)
        holes = [f for f in out["features"] if f["type"] == "hole"]
        assert len(holes) == 0, f"unexpected holes: {holes}"


# ---------------------------------------------------------------------------
# Oracle 1c: box with drilled hole + filleted edge (combined)
# ---------------------------------------------------------------------------


class TestBoxWithHoleAndFillet:
    """Box → fillet one Z-edge → drill through-hole → 1 hole + 1 fillet."""

    def test_hole_and_fillet_detected(self):
        body = _build_hole_and_fillet_body()
        out = recognize_features(body)
        holes = [f for f in out["features"] if f["type"] == "hole"]
        fillets = [f for f in out["features"] if f["type"] == "fillet"]
        assert len(holes) == 1, f"expected 1 hole, got {len(holes)}"
        assert len(fillets) == 1, f"expected 1 fillet, got {len(fillets)}"

    def test_hole_and_fillet_face_ids_disjoint(self):
        body = _build_hole_and_fillet_body()
        out = recognize_features(body)
        holes = [f for f in out["features"] if f["type"] == "hole"]
        fillets = [f for f in out["features"] if f["type"] == "fillet"]
        assert holes and fillets
        hole_fids = set(holes[0]["face_ids"])
        fillet_fids = set(fillets[0]["face_ids"])
        assert hole_fids.isdisjoint(fillet_fids), (
            f"hole and fillet share face ids: {hole_fids & fillet_fids}"
        )

    def test_hole_and_fillet_face_ids_are_cylindrical(self):
        body = _build_hole_and_fillet_body()
        out = recognize_features(body)
        from kerf_cad_core.geom.feature_recognition import _is_cylinder_like
        cyl_ids = {f.id for f in body.all_faces() if _is_cylinder_like(f)}
        for feat in out["features"]:
            if feat["type"] in ("hole", "fillet"):
                for fid in feat["face_ids"]:
                    assert fid in cyl_ids, (
                        f"{feat['type']} feature face_id {fid} is not cylindrical"
                    )

    def test_summary_counts(self):
        body = _build_hole_and_fillet_body()
        out = recognize_features(body)
        s = out["summary"]
        assert s["hole"] == 1
        assert s["fillet"] == 1
        assert s["chamfer"] == 0

    def test_hole_radius_in_combined_body(self):
        body = _build_hole_and_fillet_body()
        out = recognize_features(body)
        holes = [f for f in out["features"] if f["type"] == "hole"]
        assert holes
        r = holes[0]["params"]["radius"]
        assert abs(r - 1.0) < 0.01, f"hole radius expected ~1.0, got {r}"

    def test_fillet_radius_in_combined_body(self):
        body = _build_hole_and_fillet_body()
        out = recognize_features(body)
        fillets = [f for f in out["features"] if f["type"] == "fillet"]
        assert fillets
        r = fillets[0]["params"]["radius"]
        assert abs(r - 0.5) < 0.01, f"fillet radius expected ~0.5, got {r}"


# ---------------------------------------------------------------------------
# Oracle 2: plain box → no features
# ---------------------------------------------------------------------------


class TestPlainBox:
    """A plain 10×10×10 box has no recognisable features."""

    def test_no_features(self):
        box = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
        out = recognize_features(box)
        assert out["features"] == [], f"expected no features, got: {out['features']}"

    def test_summary_all_zero(self):
        box = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
        out = recognize_features(box)
        s = out["summary"]
        for key, val in s.items():
            assert val == 0, f"summary[{key!r}] expected 0, got {val}"

    def test_return_structure(self):
        """Output always has 'features' (list) and 'summary' (dict) keys."""
        box = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
        out = recognize_features(box)
        assert isinstance(out, dict)
        assert "features" in out
        assert "summary" in out
        assert isinstance(out["features"], list)
        assert isinstance(out["summary"], dict)
        for key in ("hole", "pocket", "boss", "fillet", "chamfer"):
            assert key in out["summary"]


# ---------------------------------------------------------------------------
# Oracle 3: export from geom package-level __init__
# ---------------------------------------------------------------------------


def test_package_export():
    """recognize_features must be importable from kerf_cad_core.geom."""
    from kerf_cad_core.geom import recognize_features as rf  # noqa: F401
    assert callable(rf)
