"""
kerf_wiring.harness3d — 3D wiring harness route-through-DMU primitive.

Provides :func:`harness_segment`, which takes a list of 3-D waypoints and a
wire list, and returns a :class:`HarnessSegment` describing the routed bundle:
its polyline path, overall bundle diameter, and total arc-length.

Design notes
------------
* **No OCCT dependency at this layer** — the primitive is pure-Python geometry.
  A downstream sweep (e.g. via occtWorker.js) consumes the path + diameter to
  produce a solid body.  Keeping the primitive dependency-free lets it run in
  any Python environment and makes it trivially testable.

* **Diameter model** — each wire contributes a cross-sectional circular area.
  The bundle diameter is derived from the total occupied area with an assumed
  packing efficiency of π/4 ≈ 0.785 (hexagonal close-packing approximation):

      bundle_area  = sum(π * (d_i/2)²) / packing_efficiency
      bundle_diam  = 2 * sqrt(bundle_area / π)

  which simplifies to:

      bundle_diam  = sqrt(sum(d_i²) / packing_efficiency)

  A 15 % slack factor is also applied so the conduit/sheath is realistically
  over-sized relative to the bare conductor bundle.

* **Path length** — Euclidean arc-length of the piecewise-linear polyline
  (sum of segment lengths).  Sufficient for formboard-flatten tasks (T-37).

* **Wire diameter defaults** — if a wire record omits ``diameter_mm``, the
  AWG-based lookup table provides a fallback (AWG 20 = 0.812 mm is a common
  automotive signal wire).

Terminology
-----------
waypoints  — list of (x, y, z) tuples in mm, at least 2 points
wire_list  — list of dicts; each dict may carry:
               name         (str, optional)
               gauge_awg    (int, optional)
               diameter_mm  (float, optional)   — overrides gauge_awg
               count        (int, optional, default 1)  — parallel wires
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

# ---------------------------------------------------------------------------
# AWG → wire-conductor diameter (mm) lookup, AWG 0–40
# Source: IEC 60228 / ANSI/AWG standard nominal values.
# ---------------------------------------------------------------------------
_AWG_DIAMETER_MM: dict[int, float] = {
    0: 8.252,
    1: 7.348,
    2: 6.544,
    3: 5.827,
    4: 5.189,
    5: 4.621,
    6: 4.115,
    7: 3.665,
    8: 3.264,
    9: 2.906,
    10: 2.588,
    11: 2.305,
    12: 2.053,
    13: 1.828,
    14: 1.628,
    15: 1.450,
    16: 1.291,
    17: 1.150,
    18: 1.024,
    19: 0.912,
    20: 0.812,
    21: 0.723,
    22: 0.644,
    23: 0.573,
    24: 0.511,
    25: 0.455,
    26: 0.405,
    27: 0.361,
    28: 0.321,
    29: 0.286,
    30: 0.255,
    31: 0.227,
    32: 0.202,
    33: 0.180,
    34: 0.160,
    35: 0.143,
    36: 0.127,
    37: 0.113,
    38: 0.101,
    39: 0.090,
    40: 0.080,
}

_DEFAULT_AWG = 20  # AWG 20 — typical automotive signal wire
_PACKING_EFFICIENCY = math.pi / 4  # hexagonal close-packing ≈ 0.785
_SLACK_FACTOR = 1.15  # 15 % sheath over-size


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

Point3D = tuple[float, float, float]


@dataclass
class WireSpec:
    """Normalised representation of a single wire (or group of parallel wires)."""
    name: str
    diameter_mm: float
    count: int = 1

    @property
    def total_area_mm2(self) -> float:
        """Sum of cross-sectional areas of all parallel wires in mm²."""
        r = self.diameter_mm / 2.0
        return self.count * math.pi * r * r


@dataclass
class HarnessSegment:
    """
    Result of :func:`harness_segment`.

    Attributes
    ----------
    waypoints       Normalised 3-D path (list of Point3D, ≥ 2 points).
    wires           Normalised wire specs used to compute the bundle.
    bundle_diameter_mm
                    Outer diameter of the routed bundle, in mm, including
                    packing slack.
    length_mm       Total arc-length of the polyline path, in mm.
    segment_lengths_mm
                    Per-segment lengths (len == len(waypoints) - 1).
    """
    waypoints: list[Point3D]
    wires: list[WireSpec]
    bundle_diameter_mm: float
    length_mm: float
    segment_lengths_mm: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def harness_segment(
    waypoints: Sequence[tuple | list],
    wire_list: Sequence[dict],
    *,
    packing_efficiency: float = _PACKING_EFFICIENCY,
    slack_factor: float = _SLACK_FACTOR,
) -> HarnessSegment:
    """
    Route a wire bundle along a 3-D polyline path.

    Parameters
    ----------
    waypoints :
        Ordered sequence of (x, y, z) tuples / lists, in mm.
        Must contain at least 2 distinct points.
    wire_list :
        Sequence of wire-spec dicts.  Each dict may contain:

        * ``name``         (str)   — identifier, optional
        * ``gauge_awg``    (int)   — AWG gauge; used when ``diameter_mm``
                                     is absent
        * ``diameter_mm``  (float) — explicit conductor outer diameter in mm;
                                     takes precedence over ``gauge_awg``
        * ``count``        (int)   — number of parallel wires, default 1

    packing_efficiency :
        Fraction of bundle cross-section occupied by conductors (0 < η ≤ 1).
        Defaults to π/4 ≈ 0.785.
    slack_factor :
        Multiplicative over-size for the sheath (≥ 1.0).
        Defaults to 1.15 (15 % slack).

    Returns
    -------
    HarnessSegment

    Raises
    ------
    ValueError
        If fewer than 2 waypoints are provided, wire_list is empty, any
        waypoint is not a 3-element sequence, or packing/slack parameters are
        out of range.
    """
    # ── validate inputs ────────────────────────────────────────────────────────
    pts = [tuple(float(c) for c in p) for p in waypoints]
    if len(pts) < 2:
        raise ValueError(
            f"harness_segment requires at least 2 waypoints; got {len(pts)}"
        )
    for i, p in enumerate(pts):
        if len(p) != 3:
            raise ValueError(
                f"waypoint[{i}] must have exactly 3 coordinates; got {p!r}"
            )
    if not wire_list:
        raise ValueError("wire_list must contain at least one wire")
    if not (0.0 < packing_efficiency <= 1.0):
        raise ValueError(
            f"packing_efficiency must be in (0, 1]; got {packing_efficiency}"
        )
    if slack_factor < 1.0:
        raise ValueError(
            f"slack_factor must be ≥ 1.0; got {slack_factor}"
        )

    # ── normalise wire specs ───────────────────────────────────────────────────
    wires: list[WireSpec] = []
    for i, w in enumerate(wire_list):
        name = str(w.get("name", f"wire_{i}"))
        count = int(w.get("count", 1))
        if count < 1:
            raise ValueError(f"wire '{name}' count must be ≥ 1; got {count}")

        if "diameter_mm" in w:
            diam = float(w["diameter_mm"])
        elif "gauge_awg" in w:
            awg = int(w["gauge_awg"])
            if awg not in _AWG_DIAMETER_MM:
                raise ValueError(
                    f"wire '{name}': AWG {awg} is not in the lookup table "
                    f"(valid range 0–40)"
                )
            diam = _AWG_DIAMETER_MM[awg]
        else:
            diam = _AWG_DIAMETER_MM[_DEFAULT_AWG]

        if diam <= 0.0:
            raise ValueError(
                f"wire '{name}' diameter_mm must be > 0; got {diam}"
            )
        wires.append(WireSpec(name=name, diameter_mm=diam, count=count))

    # ── compute bundle diameter ────────────────────────────────────────────────
    total_area = sum(w.total_area_mm2 for w in wires)
    # Invert packing: bundle_area = total_conductor_area / packing_efficiency
    bundle_area = total_area / packing_efficiency
    # Bundle outer radius from area of circle
    bundle_radius = math.sqrt(bundle_area / math.pi)
    bundle_diameter = 2.0 * bundle_radius * slack_factor

    # ── compute path length ───────────────────────────────────────────────────
    seg_lengths: list[float] = []
    for a, b in zip(pts, pts[1:]):
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        seg_lengths.append(math.sqrt(dx * dx + dy * dy + dz * dz))
    total_length = sum(seg_lengths)

    return HarnessSegment(
        waypoints=list(pts),
        wires=wires,
        bundle_diameter_mm=bundle_diameter,
        length_mm=total_length,
        segment_lengths_mm=seg_lengths,
    )


# ---------------------------------------------------------------------------
# Convenience: serialise to a JSON-friendly dict (for the LLM tool / API)
# ---------------------------------------------------------------------------

def segment_to_dict(seg: HarnessSegment) -> dict:
    """Serialise a HarnessSegment to a plain dict suitable for json.dumps."""
    return {
        "waypoints": [list(p) for p in seg.waypoints],
        "wires": [
            {
                "name": w.name,
                "diameter_mm": w.diameter_mm,
                "count": w.count,
            }
            for w in seg.wires
        ],
        "bundle_diameter_mm": seg.bundle_diameter_mm,
        "length_mm": seg.length_mm,
        "segment_lengths_mm": seg.segment_lengths_mm,
    }
