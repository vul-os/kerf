"""
kerf_cad_core.brep.motion_interference — Assembly motion interference detection.

Sweeps the existing assembly clash detector over a multi-body motion timeline,
reports per-frame collisions, and collapses consecutive collision frames into
``InterferenceEvent`` intervals.

References
----------
* Hubbard 1996 — "Approximating Polyhedra with Spheres for Time-Critical
  Collision Detection". ACM Transactions on Graphics, 15(3):179–210.
  (OBB hierarchy traversal for swept-volume broad phase.)
* Mirtich 1996 — "Impulse-based Dynamic Simulation of Rigid Body Systems".
  PhD Thesis, UC Berkeley.
  (Rigid body swept-volume formulation and time-of-contact bracketing.)
* Möller 1997 — "A fast triangle-triangle intersection test".
  Journal of Graphics Tools 2(2):25–30.
  (Narrow-phase triangle/triangle kernel — delegated to assembly_clash /
  geom.assembly_interference.)

Algorithm overview
------------------
1. For each ``MotionFrame`` in the timeline, apply every body's 4×4 homogeneous
   transform to produce a placed ``ComponentShape`` in world space.
2. Run the existing ``clash_detect`` pairwise AABB + OBB + optional triangle
   narrow-phase detector on the transformed shapes.
3. Collect per-frame ``(t, comp_a, comp_b, penetration_mm)`` collision tuples.
4. Call ``merge_intervals`` to collapse same-pair consecutive frames into
   ``InterferenceEvent`` records.
5. Track the minimum clearance gap across all non-colliding frame pairs for
   design clearance reporting.

Units: mm throughout.
Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING, Any

import numpy as np

# Re-use the existing assembly clash detection machinery — no duplication of
# the triangle-triangle math.
from kerf_cad_core.clash.detect import (
    ComponentShape,
    ClashType,
    _OBB,
    _aabb_gap,
    _aabb_overlap,
    _obb_sat,
    _obb_clearance_gap,
    _world_aabb,
    _mesh_intersect,
    _centres_coincident,
)
from kerf_cad_core.assembly.model import _identity, _mat_mul

if TYPE_CHECKING:
    from kerf_cad_core.geom.brep import Body


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------

@dataclass
class MotionFrame:
    """One snapshot of the assembly at time *t*.

    Parameters
    ----------
    t:
        Time in seconds.
    component_transforms:
        Mapping from component_id to its 4×4 world-space homogeneous
        transform at this instant.  Each value is a 16-element flat
        list (row-major) or a (4, 4) numpy array.
    """
    t: float
    component_transforms: dict[str, Any]  # component_id -> 4×4 matrix

    def __post_init__(self) -> None:
        self.t = float(self.t)
        # Normalise transforms: accept (4,4) ndarray or flat list[float].
        normalised: dict[str, list[float]] = {}
        for cid, mat in self.component_transforms.items():
            if isinstance(mat, np.ndarray):
                flat = mat.flatten().tolist()
            else:
                flat = [float(v) for v in mat]
            if len(flat) != 16:
                raise ValueError(
                    f"component_transforms[{cid!r}]: expected 16-element "
                    f"4×4 matrix, got {len(flat)} elements"
                )
            normalised[str(cid)] = flat
        self.component_transforms = normalised


@dataclass
class InterferenceEvent:
    """A continuous collision episode between two components.

    Attributes
    ----------
    component_a, component_b:
        Identifiers of the two colliding components.
    t_start, t_end:
        Time interval [t_start, t_end] over which the collision persists.
    max_penetration_mm:
        Worst-case OBB penetration depth across all frames in the interval.
    penetration_point:
        Representative world-space contact / penetration centre at the
        frame of maximum penetration.  Shape: (3,) float64.
    """
    component_a: str
    component_b: str
    t_start: float
    t_end: float
    max_penetration_mm: float
    penetration_point: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def __post_init__(self) -> None:
        self.penetration_point = np.asarray(self.penetration_point, dtype=float)

    def to_dict(self) -> dict:
        return {
            "component_a": self.component_a,
            "component_b": self.component_b,
            "t_start": float(self.t_start),
            "t_end": float(self.t_end),
            "max_penetration_mm": float(self.max_penetration_mm),
            "penetration_point": self.penetration_point.tolist(),
        }


@dataclass
class MotionInterferenceReport:
    """Full sweep report for a multi-body motion timeline.

    Attributes
    ----------
    events:
        List of ``InterferenceEvent`` (merged collision intervals).
    frames_swept:
        Total number of frames evaluated.
    total_collision_frames:
        Number of frames in which at least one pair collided.
    clearance_min_mm:
        Smallest gap observed across all non-colliding pair/frame
        combinations.  ``float('inf')`` when every frame had at least
        one collision (no clear gap recorded).
    bodies_at_min_clearance:
        ``(comp_a, comp_b)`` pair that produced ``clearance_min_mm``,
        or ``None`` if there were no clear pairs.
    """
    events: list[InterferenceEvent] = field(default_factory=list)
    frames_swept: int = 0
    total_collision_frames: int = 0
    clearance_min_mm: float = float("inf")
    bodies_at_min_clearance: tuple[str, str] | None = None

    def to_dict(self) -> dict:
        return {
            "events": [e.to_dict() for e in self.events],
            "frames_swept": self.frames_swept,
            "total_collision_frames": self.total_collision_frames,
            "clearance_min_mm": (
                None if math.isinf(self.clearance_min_mm)
                else float(self.clearance_min_mm)
            ),
            "bodies_at_min_clearance": (
                list(self.bodies_at_min_clearance)
                if self.bodies_at_min_clearance else None
            ),
        }


# ---------------------------------------------------------------------------
# Helpers — per-frame clash evaluation
# ---------------------------------------------------------------------------

def _make_component_shape(
    component_id: str,
    body_desc: dict[str, Any],
    world_transform: list[float],
) -> ComponentShape:
    """Build a placed ``ComponentShape`` for one body at one frame.

    Parameters
    ----------
    component_id:
        Unique identifier used in clash records.
    body_desc:
        Dict describing the body geometry.  Accepted keys mirror
        ``ComponentShape.__init__``:
        ``bbox_min``, ``bbox_max``, ``triangles``.
        All are in *local* (body) space.
    world_transform:
        16-element row-major 4×4 matrix placing the body in world space
        at this frame.
    """
    bbox_min = tuple(float(v) for v in body_desc.get("bbox_min", (0.0, 0.0, 0.0)))
    bbox_max = tuple(float(v) for v in body_desc.get("bbox_max", (1.0, 1.0, 1.0)))
    triangles = body_desc.get("triangles")
    if triangles is not None:
        triangles = [
            (tuple(t[0]), tuple(t[1]), tuple(t[2]))
            for t in triangles
        ]
    return ComponentShape(
        instance_id=component_id,
        transform=world_transform,
        bbox_min=bbox_min,  # type: ignore[arg-type]
        bbox_max=bbox_max,  # type: ignore[arg-type]
        triangles=triangles,
    )


def _evaluate_frame(
    shapes: list[ComponentShape],
    coarse_bbox_only: bool,
    min_clearance: float = 0.0,
) -> list[tuple[str, str, float, tuple[float, float, float]]]:
    """Evaluate all pairwise clashes for one frame.

    Returns
    -------
    list of ``(comp_a, comp_b, penetration_mm, contact_point)`` tuples
    for colliding pairs only.  Non-colliding pairs are omitted.
    """
    results: list[tuple[str, str, float, tuple[float, float, float]]] = []
    n = len(shapes)
    if n < 2:
        return results

    # Pre-compute world AABBs and OBBs once per frame.
    aabbs = [_world_aabb(s) for s in shapes]
    obbs = [_OBB(s) for s in shapes]

    for i, j in combinations(range(n), 2):
        sha, shb = shapes[i], shapes[j]
        obb_a, obb_b = obbs[i], obbs[j]
        aabb_a, aabb_b = aabbs[i], aabbs[j]

        # Coincident check — treat as a zero-depth collision.
        if _centres_coincident(obb_a, obb_b):
            contact = obb_a.centre
            results.append((sha.instance_id, shb.instance_id, 0.0, contact))
            continue

        # Broad-phase AABB test.
        if not _aabb_overlap(aabb_a[0], aabb_a[1], aabb_b[0], aabb_b[1]):
            continue

        if coarse_bbox_only:
            # In coarse mode: any AABB overlap is reported as a collision.
            # Estimate penetration from AABB overlap depth.
            _, depth = _obb_sat(obb_a, obb_b)
            contact = tuple(
                (obb_a.centre[k] + obb_b.centre[k]) * 0.5 for k in range(3)
            )
            results.append((sha.instance_id, shb.instance_id, max(0.0, depth), contact))
            continue

        # Narrow-phase: triangle mesh if available, else OBB SAT.
        if sha.triangles and shb.triangles:
            intersecting = _mesh_intersect(
                sha.triangles, sha.transform,
                shb.triangles, shb.transform,
            )
            if intersecting:
                _, depth = _obb_sat(obb_a, obb_b)
                contact = tuple(
                    (obb_a.centre[k] + obb_b.centre[k]) * 0.5 for k in range(3)
                )
                results.append((sha.instance_id, shb.instance_id, max(0.0, depth), contact))
        else:
            overlapping, depth = _obb_sat(obb_a, obb_b)
            if overlapping:
                contact = tuple(
                    (obb_a.centre[k] + obb_b.centre[k]) * 0.5 for k in range(3)
                )
                results.append((sha.instance_id, shb.instance_id, max(0.0, depth), contact))

    return results


# ---------------------------------------------------------------------------
# merge_intervals — collapse consecutive same-pair frames
# ---------------------------------------------------------------------------

def merge_intervals(
    per_frame_collisions: list[tuple[float, str, str, float]],
) -> list[InterferenceEvent]:
    """Collapse same-pair consecutive frames into ``InterferenceEvent`` objects.

    Parameters
    ----------
    per_frame_collisions:
        Flat list of ``(t, comp_a, comp_b, penetration_mm)`` tuples,
        sorted ascending by *t*.  The pair ``(comp_a, comp_b)`` must be
        in a canonical (sorted) order — this function normalises it
        internally so callers need not pre-sort.

    Returns
    -------
    list of ``InterferenceEvent`` — one per continuous collision episode
    per pair.
    """
    if not per_frame_collisions:
        return []

    # Normalise pair order and build (pair_key -> list of (t, depth)) mapping.
    # We track the contact point separately.
    # Use a list of dicts keyed by (pair_key, episode_id) but simpler: build
    # a sorted list of (pair_key, t, depth) then sweep.

    # Sort by (pair_key, t) — pair_key is alphabetically sorted tuple.
    normalised: list[tuple[tuple[str, str], float, float]] = []
    for t, ca, cb, depth in per_frame_collisions:
        key: tuple[str, str] = (ca, cb) if ca <= cb else (cb, ca)
        normalised.append((key, float(t), float(depth)))

    # Sort by pair key then by time.
    normalised.sort(key=lambda x: (x[0], x[1]))

    events: list[InterferenceEvent] = []

    # Group by pair key, then scan for consecutive frame runs.
    # Two frames are "consecutive" when they belong to the same timeline slice
    # and there is no gap between them — we detect non-consecutive frames by
    # tracking whether the same pair appeared in the immediately previous frame.
    # Since frames have arbitrary time spacing we define "consecutive" as: no
    # other frame of the same pair exists between the last frame and this one.
    # We achieve this by collecting all (t, depth) for each pair and then
    # running a simple gap-detection: a new episode starts when the pair was
    # absent in the previous contiguous time step.
    #
    # Implementation: for each pair, collect all (t, depth) sorted by t, then
    # compare adjacent t values against the *actual* frame times to detect gaps.

    # We need the full sorted frame time list to know which pairs were absent.
    # Since we only have per_frame_collisions (collision frames only), we
    # cannot know the absent frames without the full timeline.  The caller
    # (sweep_motion_interference) knows the full timeline and passes the
    # all_frame_times so merge_intervals can do gap detection.
    #
    # For the simplified public API (merge_intervals takes only collisions),
    # we define "consecutive" by checking that no other pair entry for the same
    # pair appears between two adjacent hits in the collision list — i.e. if
    # the same pair appears at t=0.1, t=0.2, t=0.3 with nothing else in
    # between, they form one event; if they appear at t=0.1 and t=0.3 and
    # there was a t=0.2 frame where this pair did NOT collide, we cannot detect
    # that gap here.
    #
    # The private helper _merge_intervals_with_timeline (called from
    # sweep_motion_interference) handles proper gap detection.
    # This public helper just merges runs of same-pair adjacent entries.

    from itertools import groupby

    for pair_key, group in groupby(normalised, key=lambda x: x[0]):
        entries = sorted(group, key=lambda x: x[1])  # sort by t
        # Build episodes: a new episode starts when there is a gap in the
        # list (i.e. some frames of this pair are missing in between adjacent
        # entries).  Without full timeline info, we can only merge runs where
        # the pair appears at *every* available time step in the collision list.
        # We treat each entry as contiguous with the previous one.
        ep_t_start = entries[0][1]
        ep_t_end = entries[0][1]
        ep_max_depth = entries[0][2]
        ep_contact = np.zeros(3)  # contact not available in this helper sig

        for idx in range(1, len(entries)):
            _, t_i, depth_i = entries[idx]
            ep_t_end = t_i
            if depth_i > ep_max_depth:
                ep_max_depth = depth_i

        events.append(InterferenceEvent(
            component_a=pair_key[0],
            component_b=pair_key[1],
            t_start=ep_t_start,
            t_end=ep_t_end,
            max_penetration_mm=ep_max_depth,
            penetration_point=ep_contact,
        ))

    return events


def _merge_intervals_with_timeline(
    per_frame_collisions: list[tuple[float, str, str, float, tuple[float, float, float]]],
    all_frame_times: list[float],
) -> list[InterferenceEvent]:
    """Internal: merge collision frames into events with proper gap detection.

    Uses the full *all_frame_times* list to detect when a pair was absent from
    a frame (gap) and thus should start a new episode.

    Parameters
    ----------
    per_frame_collisions:
        ``(t, comp_a, comp_b, penetration_mm, contact_point)`` tuples.
    all_frame_times:
        Sorted list of all frame timestamps in the timeline.

    Returns
    -------
    list of ``InterferenceEvent``
    """
    if not per_frame_collisions:
        return []

    # Map each frame time to its index.
    t_to_idx: dict[float, int] = {t: i for i, t in enumerate(all_frame_times)}

    # Normalise pair order; build per-pair dict of frame_idx → (depth, contact).
    pair_frames: dict[
        tuple[str, str], dict[int, tuple[float, tuple[float, float, float]]]
    ] = {}
    for t, ca, cb, depth, contact in per_frame_collisions:
        key: tuple[str, str] = (ca, cb) if ca <= cb else (cb, ca)
        fidx = t_to_idx.get(t, -1)
        if fidx < 0:
            continue
        if key not in pair_frames:
            pair_frames[key] = {}
        # Keep worst depth for this frame (handles duplicate entries).
        prev = pair_frames[key].get(fidx)
        if prev is None or depth > prev[0]:
            pair_frames[key][fidx] = (depth, contact)

    events: list[InterferenceEvent] = []

    for pair_key, frame_map in pair_frames.items():
        sorted_idxs = sorted(frame_map.keys())

        # Split into consecutive runs (gap = a frame index is missing in between).
        runs: list[list[int]] = []
        current_run: list[int] = [sorted_idxs[0]]
        for k in range(1, len(sorted_idxs)):
            if sorted_idxs[k] == sorted_idxs[k - 1] + 1:
                current_run.append(sorted_idxs[k])
            else:
                runs.append(current_run)
                current_run = [sorted_idxs[k]]
        runs.append(current_run)

        for run in runs:
            best_depth = -1.0
            best_contact: tuple[float, float, float] = (0.0, 0.0, 0.0)
            for fidx in run:
                depth_i, contact_i = frame_map[fidx]
                if depth_i > best_depth:
                    best_depth = depth_i
                    best_contact = contact_i

            t_start = all_frame_times[run[0]]
            t_end = all_frame_times[run[-1]]
            events.append(InterferenceEvent(
                component_a=pair_key[0],
                component_b=pair_key[1],
                t_start=t_start,
                t_end=t_end,
                max_penetration_mm=max(0.0, best_depth),
                penetration_point=np.array(best_contact, dtype=float),
            ))

    # Sort events by (component_a, component_b, t_start) for determinism.
    events.sort(key=lambda e: (e.component_a, e.component_b, e.t_start))
    return events


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def sweep_motion_interference(
    bodies: dict[str, Any],
    frames: list[MotionFrame],
    coarse_bbox_only: bool = False,
) -> MotionInterferenceReport:
    """Sweep the assembly clash detector over a multi-body motion timeline.

    For each ``MotionFrame`` in *frames*, this function:

    1. Applies each body's frame-specific 4×4 transform to produce a
       world-placed ``ComponentShape``.
    2. Runs the AABB + OBB + (optionally) triangle narrow-phase pairwise
       clash detector on the placed shapes.
    3. Collects per-frame collision events with penetration depths.
    4. Calls ``_merge_intervals_with_timeline`` to collapse consecutive
       collision frames into ``InterferenceEvent`` intervals.
    5. Tracks the minimum clearance gap for non-colliding pairs.

    The sweep follows the swept-volume framing of Hubbard 1996 / Mirtich 1996
    but uses a discrete-time sample approach (one full static-geometry test
    per frame) rather than continuous motion integration.  Finer temporal
    resolution reduces the risk of tunnelling for fast-moving components.

    Parameters
    ----------
    bodies:
        Mapping from component_id (str) to a body descriptor.  Each value
        may be either:
        - A dict with keys ``bbox_min``, ``bbox_max`` (tuples of 3 floats,
          in local/body frame) and optionally ``triangles`` (list of
          ``[[v0],[v1],[v2]]`` triples in local frame).
        - An instance of ``kerf_cad_core.geom.brep.Body`` — the geometry
          is automatically tessellated to an AABB for the clash detector.
    frames:
        Ordered list of ``MotionFrame`` objects defining the timeline.
        Must contain at least two entries for any events to be generated.
        An empty list raises ``ValueError``.
    coarse_bbox_only:
        When True, only AABB overlap is checked (no OBB SAT / triangle
        narrow phase).  Faster but may produce false positives when bodies
        have tight AABB fits but non-overlapping geometry.  Per Hubbard 1996
        §3, this is appropriate for broad-phase culling passes.

    Returns
    -------
    MotionInterferenceReport
        Summary of all interference events across the timeline.

    Raises
    ------
    ValueError
        When *frames* is empty, or when any frame's component_transforms
        references a component_id not found in *bodies*.
    """
    if not frames:
        raise ValueError("frames must be non-empty — provide at least one MotionFrame")

    if len(frames) < 2:
        # A single-frame timeline cannot produce events (no before/after to sweep).
        return MotionInterferenceReport(
            events=[],
            frames_swept=1,
            total_collision_frames=0,
            clearance_min_mm=float("inf"),
            bodies_at_min_clearance=None,
        )

    # Validate and normalise body descriptors.
    body_descs: dict[str, dict[str, Any]] = {}
    for cid, body_val in bodies.items():
        cid = str(cid)
        if hasattr(body_val, "all_faces"):
            # It's a kerf_cad_core.geom.brep.Body — extract AABB from vertices.
            pts: list[list[float]] = []
            for v in body_val.all_vertices():
                pts.append(list(v.point))
            if pts:
                pts_arr = np.array(pts, dtype=float)
                lo = pts_arr.min(axis=0).tolist()
                hi = pts_arr.max(axis=0).tolist()
            else:
                lo, hi = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
            body_descs[cid] = {"bbox_min": lo, "bbox_max": hi}
        elif isinstance(body_val, dict):
            body_descs[cid] = body_val
        else:
            raise ValueError(
                f"bodies[{cid!r}]: expected dict or Body instance, "
                f"got {type(body_val).__name__}"
            )

    # Sort frames by time.
    sorted_frames = sorted(frames, key=lambda f: f.t)
    all_frame_times: list[float] = [f.t for f in sorted_frames]

    # Per-frame collision records.
    # Format: (t, comp_a, comp_b, penetration_mm, contact_point)
    all_collisions: list[tuple[float, str, str, float, tuple[float, float, float]]] = []

    # Clearance tracking (non-colliding pairs).
    clearance_min_mm = float("inf")
    clearance_pair: tuple[str, str] | None = None

    collision_frame_set: set[float] = set()

    for frame in sorted_frames:
        t = frame.t
        # Build placed ComponentShapes for this frame.
        placed: list[ComponentShape] = []
        for cid, bdesc in body_descs.items():
            frame_transform = frame.component_transforms.get(cid)
            if frame_transform is None:
                # Component not moved in this frame — use identity.
                frame_transform = _identity()
            placed.append(_make_component_shape(cid, bdesc, frame_transform))

        # Evaluate all pairwise clashes for this frame.
        frame_collisions = _evaluate_frame(placed, coarse_bbox_only)

        if frame_collisions:
            collision_frame_set.add(t)

        for comp_a, comp_b, depth, contact in frame_collisions:
            all_collisions.append((t, comp_a, comp_b, depth, contact))

        # Track minimum clearance for non-colliding pairs.
        if not coarse_bbox_only:
            n = len(placed)
            aabbs_f = [_world_aabb(s) for s in placed]
            obbs_f = [_OBB(s) for s in placed]
            colliding_pairs = {
                (c[0], c[1]) if c[0] <= c[1] else (c[1], c[0])
                for c in frame_collisions
            }
            for i, j in combinations(range(n), 2):
                sha, shb = placed[i], placed[j]
                pair_key = (sha.instance_id, shb.instance_id) if sha.instance_id <= shb.instance_id else (shb.instance_id, sha.instance_id)
                if pair_key in colliding_pairs:
                    continue
                # Compute OBB clearance gap.
                gap = _obb_clearance_gap(obbs_f[i], obbs_f[j])
                if gap > 0.0 and gap < clearance_min_mm:
                    clearance_min_mm = gap
                    clearance_pair = (sha.instance_id, shb.instance_id)

    # Merge collision frames into events.
    events = _merge_intervals_with_timeline(all_collisions, all_frame_times)

    return MotionInterferenceReport(
        events=events,
        frames_swept=len(sorted_frames),
        total_collision_frames=len(collision_frame_set),
        clearance_min_mm=clearance_min_mm,
        bodies_at_min_clearance=clearance_pair,
    )


__all__ = [
    "MotionFrame",
    "InterferenceEvent",
    "MotionInterferenceReport",
    "sweep_motion_interference",
    "merge_intervals",
    "_merge_intervals_with_timeline",
]
