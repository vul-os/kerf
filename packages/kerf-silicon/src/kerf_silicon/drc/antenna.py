"""
Antenna check — process-step charge-accumulation DRC extension.

During photolithography and etch, metal connected to a gate (poly) that has
**not yet** reached a diffusion node via its metal stack can accumulate plasma
charge and damage the gate oxide.

The rule for each metal layer M_i is:

    antenna_ratio(net, M_i) = total_metal_area(net, up_to_M_i) / gate_area(net)

If the ratio exceeds the per-layer limit the net is flagged as a violation
*at that process step*.  A net that has a diode tap connected anywhere on
M_1..M_i is considered discharged and is not flagged regardless of its ratio.

Public API
----------
    check_antenna(layout, rules, process_steps) -> AntennaReport

Parameters
----------
layout : list[dict]
    Shapes in the same format as the DRC engine:
        {
            "layer": str,               # e.g. "met1", "poly"
            "net":   str,               # net name — REQUIRED for antenna check
            "polygon": [(x, y), ...],   # coordinates in µm² (any consistent unit)
        }
    Optional flag on a shape:
        "is_gate": bool      — True if this shape is a poly gate (contributes
                               gate_area denominator).
        "is_diode": bool     — True if this shape is a diode tap (discharges
                               the net at its process step).

rules : dict[str, float]
    Maps layer name → maximum allowed antenna ratio.
    Defaults (SKY130 approximation) are used when not supplied:
        met1 → 400, met2 → 600, met3 → 800.

process_steps : list[str]
    Ordered list of metal layers from lowest to highest (e.g.
    ["met1", "met2", "met3"]).  The check accumulates metal area
    incrementally as each step is processed.

Returns
-------
AntennaReport
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Default SKY130 antenna ratio limits (metal_area / gate_area)
# ---------------------------------------------------------------------------

SKY130_ANTENNA_LIMITS: dict[str, float] = {
    "met1": 400.0,
    "met2": 600.0,
    "met3": 800.0,
}

# ---------------------------------------------------------------------------
# Polygon area helper (Shoelace — no Shapely dependency required)
# ---------------------------------------------------------------------------

def _polygon_area(coords: list[tuple[float, float]]) -> float:
    """Return absolute area via the Shoelace formula."""
    n = len(coords)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = coords[i]
        x1, y1 = coords[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _polygon_centroid(coords: list[tuple[float, float]]) -> tuple[float, float]:
    """Return the centroid of a polygon."""
    if not coords:
        return (0.0, 0.0)
    cx = sum(x for x, _ in coords) / len(coords)
    cy = sum(y for _, y in coords) / len(coords)
    return (cx, cy)


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------

@dataclass
class AntennaViolation:
    """A single antenna-ratio violation on a net at a given process step."""
    net: str
    layer: str
    ratio: float
    limit: float
    location: tuple[float, float]
    description: str


@dataclass
class AntennaReport:
    """Aggregated result of an antenna check pass."""
    violations: list[AntennaViolation] = field(default_factory=list)
    checked_nets: int = 0

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "violations": [
                {
                    "net": v.net,
                    "layer": v.layer,
                    "ratio": v.ratio,
                    "limit": v.limit,
                    "location": v.location,
                    "description": v.description,
                }
                for v in self.violations
            ],
            "checked_nets": self.checked_nets,
            "violation_count": len(self.violations),
        }


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def check_antenna(
    layout: list[dict],
    rules: dict[str, float] | None = None,
    process_steps: list[str] | None = None,
) -> AntennaReport:
    """
    Run antenna DRC against a layout.

    Parameters
    ----------
    layout : list[dict]
        Each element must have "layer", "net", and "polygon" keys.
        Optional boolean flags: "is_gate" (marks a poly gate shape contributing
        to the denominator) and "is_diode" (marks a diode discharge tap).
    rules : dict[str, float] | None
        Layer → maximum antenna ratio.  Defaults to SKY130_ANTENNA_LIMITS when
        None.
    process_steps : list[str] | None
        Ordered metal layers from lowest to highest.  Defaults to
        ["met1", "met2", "met3"] when None.

    Returns
    -------
    AntennaReport
    """
    if rules is None:
        rules = SKY130_ANTENNA_LIMITS
    if process_steps is None:
        process_steps = list(SKY130_ANTENNA_LIMITS.keys())

    # ------------------------------------------------------------------
    # Index shapes by net
    # ------------------------------------------------------------------
    # For each net we track:
    #   gate_area    — sum of area of shapes flagged "is_gate"
    #   metal_shapes — list of (layer, area, centroid) for metal layers
    #   diode_layers — set of layers where a diode tap exists

    net_gate_area: dict[str, float] = {}
    net_metal_shapes: dict[str, list[tuple[str, float, tuple[float, float]]]] = {}
    net_diode_layers: dict[str, set[str]] = {}

    for shape in layout:
        net = shape.get("net", "")
        if not net:
            continue
        layer = shape.get("layer", "")
        coords = shape.get("polygon", [])
        if len(coords) < 3:
            continue

        area = _polygon_area(coords)
        centroid = _polygon_centroid(coords)

        if shape.get("is_gate"):
            net_gate_area[net] = net_gate_area.get(net, 0.0) + area

        if shape.get("is_diode"):
            net_diode_layers.setdefault(net, set()).add(layer)

        # Track metal area on process-step layers
        if layer in process_steps:
            net_metal_shapes.setdefault(net, []).append((layer, area, centroid))

    # ------------------------------------------------------------------
    # Determine which nets participate in the antenna check:
    # only nets that have at least one gate shape.
    # ------------------------------------------------------------------
    active_nets = set(net_gate_area.keys())

    violations: list[AntennaViolation] = []
    checked_nets = len(active_nets)

    # ------------------------------------------------------------------
    # Process step-by-step accumulation
    # ------------------------------------------------------------------
    for net in active_nets:
        gate_area = net_gate_area[net]
        if gate_area <= 0.0:
            continue

        diode_layers = net_diode_layers.get(net, set())

        # Collect diode-discharge index — the step index at which this net
        # first gains a diode tap.  Shapes at or beyond that step are safe.
        diode_step_index: int | None = None
        for idx, step_layer in enumerate(process_steps):
            if step_layer in diode_layers:
                diode_step_index = idx
                break

        # Accumulate metal area layer by layer
        cumulative_area = 0.0
        # Collect all metal shapes for this net indexed by process step
        shapes_by_step: dict[str, list[tuple[float, tuple[float, float]]]] = {}
        for layer, area, centroid in net_metal_shapes.get(net, []):
            shapes_by_step.setdefault(layer, []).append((area, centroid))

        for step_idx, step_layer in enumerate(process_steps):
            if step_layer not in shapes_by_step:
                continue

            step_shapes = shapes_by_step[step_layer]
            step_area = sum(a for a, _ in step_shapes)
            step_centroid = step_shapes[0][1]  # use first shape centroid

            cumulative_area += step_area

            # If the net is discharged at or before this step, no violation
            if diode_step_index is not None and step_idx >= diode_step_index:
                continue

            # Check ratio against the per-layer limit
            limit = rules.get(step_layer)
            if limit is None:
                continue

            ratio = cumulative_area / gate_area
            if ratio > limit:
                violations.append(
                    AntennaViolation(
                        net=net,
                        layer=step_layer,
                        ratio=ratio,
                        limit=limit,
                        location=step_centroid,
                        description=(
                            f"Antenna violation: net '{net}' on layer '{step_layer}' "
                            f"has antenna ratio {ratio:.1f} (cumulative metal area "
                            f"{cumulative_area:.3f} / gate area {gate_area:.3f}), "
                            f"exceeds limit {limit:.1f}."
                        ),
                    )
                )

    return AntennaReport(violations=violations, checked_nets=checked_nets)
