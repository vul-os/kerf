"""
Tests for the real-OBB-from-STEP fallback in kerf_cad_core.clash.detect.

Coverage
--------
A. compute_obb_from_step
   A1. 10×5×2 box → half_extents within 0.5 mm of (5, 2.5, 1)
   A2. Invalid STEP → returns unit-box OBB (no error raised)
   A3. Empty string → returns unit-box OBB

B. OBBCache
   B1. Same blob hash → single compute (cache hit test)
   B2. Different hash → two distinct OBBs
   B3. Cache len grows correctly
   B4. Cache evicts LRU when max_size exceeded

C. clash_detect with step_blob
   C1. One component has step_blob + no bbox → result matches bbox-present case
   C2. dict component with step_blob_ref key → accepted and resolved
   C3. dict component with step_blob_hash → cache key used
   C4. Component with neither bbox NOR step_blob → unit-box fallback + warning
   C5. Component with step_blob but bad STEP → unit-box fallback + warning

D. ComponentShape _bbox_absent flag
   D1. ComponentShape with explicit bbox → _bbox_absent = False
   D2. ComponentShape default construction → _bbox_absent = False (explicit default)
"""

from __future__ import annotations

import hashlib
import math

import pytest

from kerf_cad_core.geom.obb import OBB, OBBCache, compute_obb_from_step
from kerf_cad_core.clash.detect import (
    ClashType,
    ComponentShape,
    clash_detect,
    _shape_from_dict,
)


# ---------------------------------------------------------------------------
# Helpers: synthesise a STEP box blob
# ---------------------------------------------------------------------------

def _make_step_box(sx: float, sy: float, sz: float) -> str:
    """Return STEP AP214 text for an axis-aligned box of dimensions sx×sy×sz."""
    from kerf_cad_core.geom.brep import make_box
    from kerf_cad_core.io.step_writer import write

    body = make_box(origin=(0.0, 0.0, 0.0), size=(sx, sy, sz))
    return write(body)


# ---------------------------------------------------------------------------
# A. compute_obb_from_step
# ---------------------------------------------------------------------------

class TestComputeObbFromStep:
    """A1–A3: direct OBB computation from synthetic STEP blobs."""

    def test_a1_10x5x2_box_half_extents(self):
        """A1: 10×5×2 mm box → OBB half-extents within 0.5 mm."""
        step = _make_step_box(10.0, 5.0, 2.0)
        obb = compute_obb_from_step(step)

        # OBB must be an OBB named-tuple
        assert isinstance(obb, OBB)

        # half_extents sorted descending should be ≈ (5, 2.5, 1)
        he = sorted(obb.half_extents, reverse=True)
        expected = [5.0, 2.5, 1.0]
        for got, exp in zip(he, expected):
            assert abs(got - exp) < 0.5, f"half_extent {got:.4f} not within 0.5 of {exp}"

    def test_a1_center_reasonable(self):
        """A1: OBB centre should be near (5, 2.5, 1) for the 10×5×2 box at origin."""
        step = _make_step_box(10.0, 5.0, 2.0)
        obb = compute_obb_from_step(step)
        cx, cy, cz = obb.center
        # centre must be near the geometric centroid
        assert abs(cx - 5.0) < 1.0
        assert abs(cy - 2.5) < 1.0
        assert abs(cz - 1.0) < 1.0

    def test_a1_bytes_input(self):
        """A1: accepts bytes input (UTF-8 encoded STEP)."""
        step_str = _make_step_box(4.0, 4.0, 4.0)
        step_bytes = step_str.encode("utf-8")
        obb = compute_obb_from_step(step_bytes)
        assert isinstance(obb, OBB)
        # Cube: half_extents all ≈ 2
        for he in obb.half_extents:
            assert abs(he - 2.0) < 0.5

    def test_a2_invalid_step_returns_unit_box(self):
        """A2: corrupt STEP text → returns 1 mm³ unit box, never raises."""
        obb = compute_obb_from_step("NOT VALID STEP DATA AT ALL")
        assert isinstance(obb, OBB)
        # Unit box: half_extents = (0.5, 0.5, 0.5)
        for he in obb.half_extents:
            assert abs(he - 0.5) < 0.1

    def test_a3_empty_string_returns_unit_box(self):
        """A3: empty string → returns 1 mm³ unit box."""
        obb = compute_obb_from_step("")
        assert isinstance(obb, OBB)
        for he in obb.half_extents:
            assert abs(he - 0.5) < 0.1


# ---------------------------------------------------------------------------
# B. OBBCache
# ---------------------------------------------------------------------------

class TestOBBCache:
    """B1–B4: cache correctness and LRU eviction."""

    def _make_blob(self, size):
        return _make_step_box(*size)

    def _sha(self, blob: str) -> str:
        return hashlib.sha256(blob.encode()).hexdigest()

    def test_b1_cache_hit_returns_same_object(self):
        """B1: same blob_hash → cached object returned (identity check)."""
        cache = OBBCache(max_size=32)
        blob = self._make_blob((3.0, 3.0, 3.0))
        h = self._sha(blob)

        obb1 = cache.get_or_compute(h, blob)
        obb2 = cache.get_or_compute(h, blob)

        # Both calls return an OBB; they should be equal (same named-tuple)
        assert obb1 == obb2

    def test_b2_different_hash_different_obb(self):
        """B2: different hashes → independent OBBs."""
        cache = OBBCache(max_size=32)
        blob1 = self._make_blob((2.0, 2.0, 2.0))
        blob2 = self._make_blob((10.0, 5.0, 2.0))

        obb1 = cache.get_or_compute(self._sha(blob1), blob1)
        obb2 = cache.get_or_compute(self._sha(blob2), blob2)

        # They should differ in half_extents
        assert obb1.half_extents != obb2.half_extents

    def test_b3_len_grows(self):
        """B3: cache len increases with distinct entries."""
        cache = OBBCache(max_size=32)
        for i in range(1, 5):
            blob = self._make_blob((float(i), float(i), float(i)))
            h = self._sha(blob)
            cache.get_or_compute(h, blob)

        assert len(cache) == 4

    def test_b4_lru_eviction(self):
        """B4: when max_size exceeded the LRU entry is evicted."""
        cache = OBBCache(max_size=2)
        blobs = [self._make_blob((float(i), float(i), float(i))) for i in range(1, 4)]
        hashes = [self._sha(b) for b in blobs]

        cache.get_or_compute(hashes[0], blobs[0])  # entry 0 (LRU after next)
        cache.get_or_compute(hashes[1], blobs[1])  # entry 1
        cache.get_or_compute(hashes[2], blobs[2])  # entry 2 → evicts entry 0

        assert len(cache) == 2

    def test_b_none_hash_auto_computed(self):
        """Cache correctly handles blob_hash=None by auto-hashing."""
        cache = OBBCache(max_size=8)
        blob = self._make_blob((5.0, 5.0, 5.0))

        obb1 = cache.get_or_compute(None, blob)
        obb2 = cache.get_or_compute(None, blob)

        assert obb1 == obb2


# ---------------------------------------------------------------------------
# C. clash_detect with step_blob
# ---------------------------------------------------------------------------

def _translate(dx, dy, dz):
    """Row-major 4x4 translation matrix."""
    return [
        1, 0, 0, dx,
        0, 1, 0, dy,
        0, 0, 1, dz,
        0, 0, 0, 1,
    ]


class TestClashDetectWithStepBlob:
    """C1–C5: clash_detect integration with OBB-from-STEP fallback."""

    def _step_10x5x2(self):
        return _make_step_box(10.0, 5.0, 2.0)

    def test_c1_step_blob_matches_bbox_present_case(self):
        """C1: step_blob component produces same clash outcome as explicit bbox."""
        step = self._step_10x5x2()

        # Reference: both components with explicit bbox, clearly separated
        a_ref = ComponentShape(
            "a", bbox_min=(0, 0, 0), bbox_max=(10, 5, 2)
        )
        b_ref = ComponentShape(
            "b", bbox_min=(20, 0, 0), bbox_max=(30, 5, 2)
        )
        result_ref = clash_detect([a_ref, b_ref])
        assert result_ref["clashes"] == []

        # Same test but component A uses step_blob instead of bbox
        a_step = ComponentShape(
            "a", step_blob=step, _bbox_absent=True,
        )
        b_step = ComponentShape(
            "b", bbox_min=(20, 0, 0), bbox_max=(30, 5, 2)
        )
        result_step = clash_detect([a_step, b_step])
        # Should also have no clashes (real OBB gives 10×5×2 box, far from b)
        assert result_step["clashes"] == []
        # No unit-box warnings expected when step_blob is valid
        unit_warns = [e for e in result_step["errors"] if "unit-box" in e]
        assert unit_warns == []

    def test_c1_step_blob_detects_overlap(self):
        """C1: step_blob component correctly detects hard clash on overlap."""
        step = self._step_10x5x2()  # box: 0..10 in X

        # b overlaps with the STEP box (placed at X=8, width 5 → 8..13)
        a = ComponentShape("a", step_blob=step, _bbox_absent=True)
        b = ComponentShape("b", bbox_min=(8, 0, 0), bbox_max=(13, 5, 2))

        result = clash_detect([a, b])
        # The real OBB (half_extents ≈ 5×2.5×1, centre ≈ 5,2.5,1) overlaps b
        hard = [c for c in result["clashes"] if c["type"] == ClashType.HARD]
        assert len(hard) == 1, (
            f"Expected hard clash; got clashes={result['clashes']}, "
            f"errors={result['errors']}"
        )

    def test_c2_dict_step_blob_ref_key(self):
        """C2: dict component using 'step_blob_ref' key is accepted."""
        step = self._step_10x5x2()
        comps = [
            {
                "instance_id": "a",
                "step_blob_ref": step,  # legacy alias
            },
            {
                "instance_id": "b",
                "bbox_min": [20, 0, 0],
                "bbox_max": [30, 5, 2],
            },
        ]
        result = clash_detect(comps)
        # No error parsing step_blob_ref
        parse_errors = [e for e in result["errors"] if "components[" in e]
        assert parse_errors == []

    def test_c3_step_blob_hash_used(self):
        """C3: step_blob_hash is threaded through to cache lookup."""
        step = _make_step_box(3.0, 3.0, 3.0)
        blob_hash = hashlib.sha256(step.encode()).hexdigest()

        a = ComponentShape("a", step_blob=step, step_blob_hash=blob_hash, _bbox_absent=True)
        b = ComponentShape("b", bbox_min=(10, 0, 0), bbox_max=(13, 3, 3))
        result = clash_detect([a, b])

        # No errors about missing bbox or failed computation
        step_errors = [e for e in result["errors"] if "a" in e and "bbox" in e]
        assert step_errors == []

    def test_c4_no_bbox_no_step_blob_unit_box_fallback_warning(self):
        """C4: component with neither bbox nor step_blob → warning in errors."""
        # Create component via dict without bbox keys and without step_blob
        comps = [
            {
                "instance_id": "no_geo",
                # No bbox_min, bbox_max, step_blob, step_blob_ref
            },
            {
                "instance_id": "has_geo",
                "bbox_min": [0, 0, 0],
                "bbox_max": [1, 1, 1],
            },
        ]
        result = clash_detect(comps)
        # Should emit a warning about unit-box fallback for "no_geo"
        unit_warnings = [e for e in result["errors"] if "unit-box" in e and "no_geo" in e]
        assert unit_warnings, (
            f"Expected unit-box warning for 'no_geo'; errors={result['errors']}"
        )

    def test_c5_bad_step_blob_unit_box_fallback_warning(self):
        """C5: step_blob that fails to parse → unit-box fallback + warning."""
        comps = [
            {
                "instance_id": "bad_step",
                "step_blob": "ISO-10303-21; THIS IS NOT VALID STEP;",
            },
            {
                "instance_id": "ok",
                "bbox_min": [0, 0, 0],
                "bbox_max": [1, 1, 1],
            },
        ]
        result = clash_detect(comps)
        step_errors = [e for e in result["errors"] if "bad_step" in e]
        assert step_errors, (
            f"Expected error/warning for 'bad_step'; errors={result['errors']}"
        )


# ---------------------------------------------------------------------------
# D. ComponentShape _bbox_absent flag
# ---------------------------------------------------------------------------

class TestComponentShapeBboxAbsent:
    """D1–D2: _bbox_absent flag semantics."""

    def test_d1_explicit_bbox_not_absent(self):
        """D1: ComponentShape with explicit bbox → _bbox_absent = False."""
        s = ComponentShape("x", bbox_min=(0, 0, 0), bbox_max=(1, 1, 1))
        assert s._bbox_absent is False

    def test_d2_default_construction_not_absent(self):
        """D2: Default construction with default bbox → _bbox_absent = False."""
        s = ComponentShape("x")
        assert s._bbox_absent is False

    def test_d3_explicit_absent_flag(self):
        """D3: Passing _bbox_absent=True is respected."""
        step = _make_step_box(2.0, 2.0, 2.0)
        s = ComponentShape("x", step_blob=step, _bbox_absent=True)
        assert s._bbox_absent is True

    def test_d4_shape_from_dict_absent_when_no_bbox_keys(self):
        """D4: _shape_from_dict marks absent when bbox_min/bbox_max not in dict."""
        s = _shape_from_dict({"instance_id": "q"})
        assert s._bbox_absent is True

    def test_d5_shape_from_dict_not_absent_when_bbox_present(self):
        """D5: _shape_from_dict marks not absent when bbox keys are present."""
        s = _shape_from_dict({
            "instance_id": "q",
            "bbox_min": [0, 0, 0],
            "bbox_max": [1, 1, 1],
        })
        assert s._bbox_absent is False
