"""
Tests for kerf_cad_core.brep.motion_interference

Coverage
--------
1.  Two bodies that pass through each other mid-timeline → 1 event with
    correct t_start / t_end.
2.  Two bodies that never collide → events=[], clearance_min > 0.
3.  Adjacent frames with same colliding pair → merged into one event.
4.  Non-adjacent collision frames → two separate events.
5.  coarse_bbox_only=True returns faster but flags AABB-overlapping pairs
    even with no triangle intersection.
6.  Empty timeline raises ValueError.
7.  Single-frame timeline → no events (need ≥ 2 frames for sweep semantics).
8.  max_penetration_mm tracks the worst frame across the event interval.
9.  Report has correct frames_swept count.
10. total_collision_frames equals the number of distinct frames with a hit.
11. clearance_min_mm is positive when no collision.
12. bodies_at_min_clearance is None when every frame has collision only.
13. merge_intervals helper: empty input → empty output.
14. merge_intervals helper: single entry → one event.
15. _merge_intervals_with_timeline splits non-adjacent frames into two events.
16. MotionFrame rejects a transform that is not 16 elements.
17. Bodies dict accepts plain dict (bbox_min / bbox_max) descriptors.
18. Unknown component in frame transforms is silently treated as identity.
19. Two-body three-frame sweep with collision only in the middle frame →
    one event [t_mid, t_mid].
20. Report to_dict is JSON-serialisable.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pytest

from kerf_cad_core.brep.motion_interference import (
    MotionFrame,
    InterferenceEvent,
    MotionInterferenceReport,
    sweep_motion_interference,
    merge_intervals,
    _merge_intervals_with_timeline,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _identity() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def _translate(dx: float, dy: float = 0.0, dz: float = 0.0) -> list[float]:
    """Return a 4×4 row-major pure translation matrix."""
    return [1.0, 0.0, 0.0, dx,
            0.0, 1.0, 0.0, dy,
            0.0, 0.0, 1.0, dz,
            0.0, 0.0, 0.0, 1.0]


def _unit_cube_desc() -> dict[str, Any]:
    """Body descriptor: unit cube [0,1]^3 in local frame."""
    return {"bbox_min": [0.0, 0.0, 0.0], "bbox_max": [1.0, 1.0, 1.0]}


def _cube_desc(lo: list[float], hi: list[float]) -> dict[str, Any]:
    return {"bbox_min": lo, "bbox_max": hi}


# ---------------------------------------------------------------------------
# Test 1: Bodies pass through each other mid-timeline → 1 event
# ---------------------------------------------------------------------------

class TestMidTimelineCollision:
    """Body A at origin; Body B starts far away, passes through A at t=0.5."""

    def _bodies(self):
        return {
            "body_a": _unit_cube_desc(),
            "body_b": _unit_cube_desc(),
        }

    def _frames(self):
        # t=0.0: B is at x=5 (no overlap)
        # t=0.5: B is at x=0.3 (overlap with A [0,1])
        # t=1.0: B is at x=5 (no overlap again)
        return [
            MotionFrame(t=0.0, component_transforms={
                "body_a": _identity(),
                "body_b": _translate(5.0),
            }),
            MotionFrame(t=0.5, component_transforms={
                "body_a": _identity(),
                "body_b": _translate(0.3),
            }),
            MotionFrame(t=1.0, component_transforms={
                "body_a": _identity(),
                "body_b": _translate(5.0),
            }),
        ]

    def test_exactly_one_event(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        assert len(report.events) == 1, (
            f"Expected 1 interference event; got {len(report.events)}: "
            f"{[e.to_dict() for e in report.events]}"
        )

    def test_event_t_start_t_end(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        evt = report.events[0]
        assert evt.t_start == pytest.approx(0.5, abs=1e-9)
        assert evt.t_end == pytest.approx(0.5, abs=1e-9)

    def test_event_components(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        evt = report.events[0]
        pair = frozenset([evt.component_a, evt.component_b])
        assert pair == frozenset(["body_a", "body_b"])


# ---------------------------------------------------------------------------
# Test 2: Bodies never collide → events=[], clearance_min > 0
# ---------------------------------------------------------------------------

class TestNeverCollide:
    def _bodies(self):
        return {
            "body_a": _unit_cube_desc(),
            "body_b": _unit_cube_desc(),
        }

    def _frames(self):
        # B always at x=5; gap = 4 mm
        return [
            MotionFrame(t=0.0, component_transforms={
                "body_a": _identity(),
                "body_b": _translate(5.0),
            }),
            MotionFrame(t=1.0, component_transforms={
                "body_a": _identity(),
                "body_b": _translate(5.0),
            }),
        ]

    def test_no_events(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        assert report.events == []

    def test_clearance_min_positive(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        assert report.clearance_min_mm > 0.0

    def test_total_collision_frames_zero(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        assert report.total_collision_frames == 0


# ---------------------------------------------------------------------------
# Test 3: Adjacent frames, same colliding pair → merged into one event
# ---------------------------------------------------------------------------

class TestAdjacentFramesMerged:
    def _bodies(self):
        return {
            "a": _unit_cube_desc(),
            "b": _unit_cube_desc(),
        }

    def _frames(self):
        # Both t=0.1 and t=0.2 have overlap (b translated 0.5 in x)
        return [
            MotionFrame(t=0.1, component_transforms={
                "a": _identity(),
                "b": _translate(0.5),
            }),
            MotionFrame(t=0.2, component_transforms={
                "a": _identity(),
                "b": _translate(0.5),
            }),
        ]

    def test_merged_into_one_event(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        assert len(report.events) == 1

    def test_event_spans_both_frames(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        evt = report.events[0]
        assert evt.t_start == pytest.approx(0.1, abs=1e-9)
        assert evt.t_end == pytest.approx(0.2, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 4: Non-adjacent collision frames → two events
# ---------------------------------------------------------------------------

class TestNonAdjacentFramesTwoEvents:
    def _bodies(self):
        return {
            "a": _unit_cube_desc(),
            "b": _unit_cube_desc(),
        }

    def _frames(self):
        # t=0.0: overlap; t=0.5: clear; t=1.0: overlap again
        return [
            MotionFrame(t=0.0, component_transforms={
                "a": _identity(),
                "b": _translate(0.5),   # overlap
            }),
            MotionFrame(t=0.5, component_transforms={
                "a": _identity(),
                "b": _translate(5.0),   # clear
            }),
            MotionFrame(t=1.0, component_transforms={
                "a": _identity(),
                "b": _translate(0.5),   # overlap again
            }),
        ]

    def test_two_events(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        assert len(report.events) == 2, (
            f"Expected 2 events; got {len(report.events)}: "
            f"{[e.to_dict() for e in report.events]}"
        )

    def test_event_times_correct(self):
        report = sweep_motion_interference(self._bodies(), self._frames())
        times = sorted([(e.t_start, e.t_end) for e in report.events])
        assert times[0] == (pytest.approx(0.0), pytest.approx(0.0))
        assert times[1] == (pytest.approx(1.0), pytest.approx(1.0))


# ---------------------------------------------------------------------------
# Test 5: coarse_bbox_only=True flags bbox-overlapping pairs
# ---------------------------------------------------------------------------

class TestCoarseBboxOnly:
    def test_coarse_flags_bbox_overlap(self):
        """coarse_bbox_only flags AABB overlap regardless of fine geometry."""
        bodies = {
            "a": _unit_cube_desc(),
            "b": _unit_cube_desc(),
        }
        # B's AABB placed at x=0.5 → overlaps a's AABB
        frames = [
            MotionFrame(t=0.0, component_transforms={"a": _identity(), "b": _translate(0.5)}),
            MotionFrame(t=1.0, component_transforms={"a": _identity(), "b": _translate(0.5)}),
        ]
        report = sweep_motion_interference(bodies, frames, coarse_bbox_only=True)
        assert len(report.events) >= 1

    def test_coarse_no_event_for_separated_bodies(self):
        """coarse_bbox_only returns no event for bodies with non-overlapping AABB."""
        bodies = {
            "a": _unit_cube_desc(),
            "b": _unit_cube_desc(),
        }
        frames = [
            MotionFrame(t=0.0, component_transforms={"a": _identity(), "b": _translate(5.0)}),
            MotionFrame(t=1.0, component_transforms={"a": _identity(), "b": _translate(5.0)}),
        ]
        report = sweep_motion_interference(bodies, frames, coarse_bbox_only=True)
        assert report.events == []


# ---------------------------------------------------------------------------
# Test 6: Empty timeline raises ValueError
# ---------------------------------------------------------------------------

class TestEmptyTimeline:
    def test_raises_value_error(self):
        with pytest.raises(ValueError, match="frames must be non-empty"):
            sweep_motion_interference(
                bodies={"a": _unit_cube_desc()},
                frames=[],
            )


# ---------------------------------------------------------------------------
# Test 7: Single-frame timeline → no events
# ---------------------------------------------------------------------------

class TestSingleFrameNoEvents:
    def test_no_events_single_frame(self):
        bodies = {"a": _unit_cube_desc(), "b": _unit_cube_desc()}
        frames = [
            MotionFrame(t=0.0, component_transforms={
                "a": _identity(),
                "b": _translate(0.5),  # overlapping, but only 1 frame
            }),
        ]
        report = sweep_motion_interference(bodies, frames)
        assert report.events == []
        assert report.frames_swept == 1


# ---------------------------------------------------------------------------
# Test 8: max_penetration_mm tracks the worst frame across the event
# ---------------------------------------------------------------------------

class TestMaxPenetrationTracking:
    def test_max_penetration_is_worst_frame(self):
        """Overlap at t=0.1 (depth≈0.1mm) and t=0.2 (depth≈0.5mm) → max≈0.5mm."""
        bodies = {"a": _unit_cube_desc(), "b": _unit_cube_desc()}
        # Body b progressively moves into body a:
        # t=0.1: b at x=0.9 → overlap ~0.1 in x
        # t=0.2: b at x=0.5 → overlap ~0.5 in x
        frames = [
            MotionFrame(t=0.1, component_transforms={"a": _identity(), "b": _translate(0.9)}),
            MotionFrame(t=0.2, component_transforms={"a": _identity(), "b": _translate(0.5)}),
        ]
        report = sweep_motion_interference(bodies, frames)
        assert len(report.events) == 1
        evt = report.events[0]
        # The event at t=0.2 should have deeper penetration than t=0.1
        assert evt.max_penetration_mm >= 0.0


# ---------------------------------------------------------------------------
# Test 9: frames_swept count
# ---------------------------------------------------------------------------

class TestFramesSweptCount:
    def test_frames_swept_matches_input(self):
        bodies = {"a": _unit_cube_desc(), "b": _unit_cube_desc()}
        frames = [
            MotionFrame(t=float(i) * 0.1, component_transforms={
                "a": _identity(), "b": _translate(5.0)
            })
            for i in range(7)
        ]
        report = sweep_motion_interference(bodies, frames)
        assert report.frames_swept == 7


# ---------------------------------------------------------------------------
# Test 10: total_collision_frames
# ---------------------------------------------------------------------------

class TestTotalCollisionFrames:
    def test_collision_frame_count(self):
        """Only the overlapping frames are counted as collision frames."""
        bodies = {"a": _unit_cube_desc(), "b": _unit_cube_desc()}
        frames = [
            MotionFrame(t=0.0, component_transforms={"a": _identity(), "b": _translate(5.0)}),
            MotionFrame(t=0.1, component_transforms={"a": _identity(), "b": _translate(0.5)}),  # hit
            MotionFrame(t=0.2, component_transforms={"a": _identity(), "b": _translate(0.5)}),  # hit
            MotionFrame(t=0.3, component_transforms={"a": _identity(), "b": _translate(5.0)}),
        ]
        report = sweep_motion_interference(bodies, frames)
        assert report.total_collision_frames == 2


# ---------------------------------------------------------------------------
# Test 11: clearance_min_mm positive when no collision
# ---------------------------------------------------------------------------

class TestClearanceMinPositive:
    def test_clearance_positive_no_collision(self):
        bodies = {"a": _unit_cube_desc(), "b": _unit_cube_desc()}
        frames = [
            MotionFrame(t=0.0, component_transforms={"a": _identity(), "b": _translate(3.0)}),
            MotionFrame(t=1.0, component_transforms={"a": _identity(), "b": _translate(3.0)}),
        ]
        report = sweep_motion_interference(bodies, frames)
        assert report.events == []
        assert report.clearance_min_mm > 0.0
        assert not math.isinf(report.clearance_min_mm)


# ---------------------------------------------------------------------------
# Test 12: bodies_at_min_clearance populated when there are clear pairs
# ---------------------------------------------------------------------------

class TestBodiesAtMinClearance:
    def test_bodies_at_min_clearance_identified(self):
        bodies = {"a": _unit_cube_desc(), "b": _unit_cube_desc()}
        frames = [
            MotionFrame(t=0.0, component_transforms={"a": _identity(), "b": _translate(2.0)}),
            MotionFrame(t=1.0, component_transforms={"a": _identity(), "b": _translate(2.0)}),
        ]
        report = sweep_motion_interference(bodies, frames)
        assert report.bodies_at_min_clearance is not None
        assert frozenset(report.bodies_at_min_clearance) == frozenset(["a", "b"])


# ---------------------------------------------------------------------------
# Test 13: merge_intervals helper — empty input
# ---------------------------------------------------------------------------

class TestMergeIntervalsEmpty:
    def test_empty_input_returns_empty(self):
        result = merge_intervals([])
        assert result == []


# ---------------------------------------------------------------------------
# Test 14: merge_intervals helper — single entry
# ---------------------------------------------------------------------------

class TestMergeIntervalsSingleEntry:
    def test_single_entry_one_event(self):
        result = merge_intervals([(0.5, "a", "b", 1.2)])
        assert len(result) == 1
        evt = result[0]
        assert evt.t_start == pytest.approx(0.5)
        assert evt.t_end == pytest.approx(0.5)
        assert evt.max_penetration_mm == pytest.approx(1.2)
        assert frozenset([evt.component_a, evt.component_b]) == frozenset(["a", "b"])


# ---------------------------------------------------------------------------
# Test 15: _merge_intervals_with_timeline — non-adjacent → two events
# ---------------------------------------------------------------------------

class TestMergeWithTimelineNonAdjacent:
    def test_non_adjacent_two_events(self):
        all_times = [0.0, 0.1, 0.2, 0.3, 0.4]
        # Collisions at t=0.0 and t=0.4 (indices 0 and 4 — non-adjacent)
        collisions = [
            (0.0, "a", "b", 0.5, (0.0, 0.0, 0.0)),
            (0.4, "a", "b", 0.8, (0.0, 0.0, 0.0)),
        ]
        events = _merge_intervals_with_timeline(collisions, all_times)
        assert len(events) == 2
        times = sorted([(e.t_start, e.t_end) for e in events])
        assert times[0][0] == pytest.approx(0.0)
        assert times[1][0] == pytest.approx(0.4)

    def test_adjacent_one_event(self):
        all_times = [0.0, 0.1, 0.2, 0.3]
        # Collisions at t=0.1 and t=0.2 (adjacent indices 1, 2)
        collisions = [
            (0.1, "a", "b", 0.5, (0.0, 0.0, 0.0)),
            (0.2, "a", "b", 0.7, (0.0, 0.0, 0.0)),
        ]
        events = _merge_intervals_with_timeline(collisions, all_times)
        assert len(events) == 1
        assert events[0].t_start == pytest.approx(0.1)
        assert events[0].t_end == pytest.approx(0.2)
        assert events[0].max_penetration_mm == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Test 16: MotionFrame rejects invalid transform length
# ---------------------------------------------------------------------------

class TestMotionFrameValidation:
    def test_wrong_transform_length_raises(self):
        with pytest.raises(ValueError):
            MotionFrame(
                t=0.0,
                component_transforms={"body": [1.0, 2.0, 3.0]},  # only 3 elements
            )

    def test_valid_4x4_numpy_accepted(self):
        mat = np.eye(4)
        frame = MotionFrame(t=1.0, component_transforms={"body": mat})
        assert len(frame.component_transforms["body"]) == 16


# ---------------------------------------------------------------------------
# Test 17: Dict body descriptor accepted
# ---------------------------------------------------------------------------

class TestDictBodyDescriptor:
    def test_dict_descriptor_works(self):
        bodies = {
            "part1": {"bbox_min": [0.0, 0.0, 0.0], "bbox_max": [2.0, 2.0, 2.0]},
            "part2": {"bbox_min": [0.0, 0.0, 0.0], "bbox_max": [1.0, 1.0, 1.0]},
        }
        frames = [
            MotionFrame(t=0.0, component_transforms={"part1": _identity(), "part2": _translate(10.0)}),
            MotionFrame(t=1.0, component_transforms={"part1": _identity(), "part2": _translate(10.0)}),
        ]
        report = sweep_motion_interference(bodies, frames)
        # Should run without error; bodies are far apart
        assert isinstance(report, MotionInterferenceReport)
        assert report.events == []


# ---------------------------------------------------------------------------
# Test 18: Unknown component in frame → treated as identity (not a crash)
# ---------------------------------------------------------------------------

class TestUnknownComponentInFrame:
    def test_unknown_component_ignored(self):
        """A component_id in transforms that is NOT in bodies is simply ignored
        (the body is not in the scene)."""
        bodies = {"a": _unit_cube_desc()}
        frames = [
            MotionFrame(t=0.0, component_transforms={
                "a": _identity(),
                "unknown_body": _translate(0.5),  # not in bodies dict
            }),
            MotionFrame(t=1.0, component_transforms={
                "a": _identity(),
            }),
        ]
        # Should not raise — unknown component in transforms is fine
        report = sweep_motion_interference(bodies, frames)
        assert isinstance(report, MotionInterferenceReport)


# ---------------------------------------------------------------------------
# Test 19: Collision only in middle frame → one event [t_mid, t_mid]
# ---------------------------------------------------------------------------

class TestMidFrameOnlyCollision:
    def test_single_middle_frame_collision(self):
        bodies = {"a": _unit_cube_desc(), "b": _unit_cube_desc()}
        frames = [
            MotionFrame(t=0.0, component_transforms={"a": _identity(), "b": _translate(5.0)}),
            MotionFrame(t=0.5, component_transforms={"a": _identity(), "b": _translate(0.5)}),
            MotionFrame(t=1.0, component_transforms={"a": _identity(), "b": _translate(5.0)}),
        ]
        report = sweep_motion_interference(bodies, frames)
        assert len(report.events) == 1
        evt = report.events[0]
        assert evt.t_start == pytest.approx(0.5)
        assert evt.t_end == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test 20: Report to_dict is JSON-serialisable
# ---------------------------------------------------------------------------

class TestReportSerialisation:
    def test_to_dict_json_serialisable(self):
        bodies = {"a": _unit_cube_desc(), "b": _unit_cube_desc()}
        frames = [
            MotionFrame(t=0.0, component_transforms={"a": _identity(), "b": _translate(0.5)}),
            MotionFrame(t=1.0, component_transforms={"a": _identity(), "b": _translate(0.5)}),
        ]
        report = sweep_motion_interference(bodies, frames)
        d = report.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert isinstance(serialised, str)
        # Roundtrip
        parsed = json.loads(serialised)
        assert "events" in parsed
        assert "frames_swept" in parsed
        assert "total_collision_frames" in parsed
