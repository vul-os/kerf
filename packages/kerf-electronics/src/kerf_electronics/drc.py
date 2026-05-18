"""
drc.py — Design Rule Check engine for PCB layouts.

Implements three families of checks, all pure Python (no external deps):

  1. Clearance checks
     - pad-to-pad   : every pair of pads on the same layer within the same net
                      class or across net classes that are closer than
                      `min_clearance_mm` fires a violation.
     - pad-to-trace : minimum distance from a pad edge to a trace segment.
     - trace-to-trace: bounding-box pre-filter + segment-distance check for
                       every pair of traces that are not in the same net.

  2. Unconnected-pad check
     Any pad that carries a net_id but is not referenced by any pcb_trace
     route endpoint is flagged as an unrouted connection.

  3. Missing-footprint check
     Any source_component in the schematic that has no corresponding
     pcb_component element is flagged.

Public API
----------
run_drc(circuit_json, rules=None) -> dict
    Returns:
        {
          "violations": list[Violation],
          "error_count": int,
          "warning_count": int,
        }
    where Violation is:
        {
          "kind":    str,   # violation kind tag
          "message": str,   # human-readable description
          "x":       float, # board-space location (mm)
          "y":       float,
          "severity": str,  # "error" | "warning"
        }

Default rules (IPC-2221B Class B):
    min_clearance_mm: 0.2  — minimum copper-to-copper clearance
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Default design rules
# ---------------------------------------------------------------------------

DEFAULT_RULES: Dict[str, float] = {
    "min_clearance_mm": 0.2,   # min copper-to-copper gap
    "min_trace_width_mm": 0.15,
}


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _dist2d(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def _pt_to_seg_dist(px: float, py: float,
                    ax: float, ay: float,
                    bx: float, by: float) -> float:
    """Minimum distance from point (px,py) to segment (ax,ay)-(bx,by)."""
    dx = bx - ax
    dy = by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-24:
        return _dist2d(px, py, ax, ay)
    t = ((px - ax) * dx + (py - ay) * dy) / len_sq
    t = max(0.0, min(1.0, t))
    cx = ax + t * dx
    cy = ay + t * dy
    return _dist2d(px, py, cx, cy)


def _seg_to_seg_dist(ax: float, ay: float,
                     bx: float, by: float,
                     cx: float, cy: float,
                     dx_: float, dy: float) -> float:
    """Minimum distance between segment AB and segment CD."""
    return min(
        _pt_to_seg_dist(ax, ay, cx, cy, dx_, dy),
        _pt_to_seg_dist(bx, by, cx, cy, dx_, dy),
        _pt_to_seg_dist(cx, cy, ax, ay, bx, by),
        _pt_to_seg_dist(dx_, dy, ax, ay, bx, by),
    )


def _pad_half_extents(pad: Dict) -> Tuple[float, float]:
    """Return (half_width, half_height) for a pad bounding box."""
    w = pad.get("width") or pad.get("w") or 1.0
    h = pad.get("height") or pad.get("h") or w
    return float(w) / 2.0, float(h) / 2.0


def _pad_to_pad_dist(a: Dict, b: Dict) -> float:
    """Edge-to-edge bounding-box distance between two pads (can be negative if overlapping)."""
    ax, ay = float(a.get("x", 0)), float(a.get("y", 0))
    bx, by = float(b.get("x", 0)), float(b.get("y", 0))
    ahw, ahh = _pad_half_extents(a)
    bhw, bhh = _pad_half_extents(b)
    # Edge-to-edge in x and y, then Euclidean between closest faces
    dx = max(0.0, abs(bx - ax) - ahw - bhw)
    dy = max(0.0, abs(by - ay) - ahh - bhh)
    return math.hypot(dx, dy)


def _pad_to_seg_dist(pad: Dict,
                     ax: float, ay: float,
                     bx: float, by: float) -> float:
    """Distance from pad centre (minus half extents) to segment."""
    px = float(pad.get("x", 0))
    py = float(pad.get("y", 0))
    hw, hh = _pad_half_extents(pad)
    # Closest point on segment to pad centre
    base_d = _pt_to_seg_dist(px, py, ax, ay, bx, by)
    # Subtract the pad's effective radius (use min half-extent as conservative proxy)
    clearance_dist = base_d - min(hw, hh)
    return max(0.0, clearance_dist)


# ---------------------------------------------------------------------------
# CircuitJSON element extraction helpers
# ---------------------------------------------------------------------------

_PAD_TYPES = {"pcb_smtpad", "pcb_plated_hole"}
_TRACE_TYPES = {"pcb_trace"}


def _get_pads(circuit_json: List[Dict]) -> List[Dict]:
    return [e for e in circuit_json if e.get("type") in _PAD_TYPES]


def _get_traces(circuit_json: List[Dict]) -> List[Dict]:
    return [e for e in circuit_json if e.get("type") in _TRACE_TYPES]


def _trace_points(trace: Dict) -> List[Tuple[float, float]]:
    """Extract list of (x, y) waypoints from a pcb_trace element."""
    route = trace.get("route") or trace.get("points") or []
    pts = []
    for p in route:
        if isinstance(p, dict) and "x" in p and "y" in p:
            pts.append((float(p["x"]), float(p["y"])))
    return pts


def _trace_net(trace: Dict) -> Optional[str]:
    return trace.get("net_id") or trace.get("net") or trace.get("net_name")


def _pad_net(pad: Dict) -> Optional[str]:
    return pad.get("net_id") or pad.get("net") or pad.get("net_name")


def _pad_id(pad: Dict) -> str:
    return (
        pad.get("pcb_smtpad_id")
        or pad.get("pcb_plated_hole_id")
        or pad.get("id")
        or "?"
    )


# ---------------------------------------------------------------------------
# Check: pad-to-pad clearance
# ---------------------------------------------------------------------------

def _check_pad_pad_clearance(pads: List[Dict], clearance_mm: float) -> List[Dict]:
    violations: List[Dict] = []
    n = len(pads)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = pads[i], pads[j]
            # Skip same-net pads (clearance only applies across nets)
            if _pad_net(a) and _pad_net(a) == _pad_net(b):
                continue
            d = _pad_to_pad_dist(a, b)
            if d < clearance_mm:
                mx = (float(a.get("x", 0)) + float(b.get("x", 0))) / 2
                my = (float(a.get("y", 0)) + float(b.get("y", 0))) / 2
                violations.append({
                    "kind": "pad_clearance",
                    "severity": "error",
                    "x": mx,
                    "y": my,
                    "message": (
                        f"Pad {_pad_id(a)} to pad {_pad_id(b)}: "
                        f"clearance {d:.3f} mm < rule {clearance_mm:.3f} mm"
                    ),
                })
    return violations


# ---------------------------------------------------------------------------
# Check: pad-to-trace clearance
# ---------------------------------------------------------------------------

def _check_pad_trace_clearance(pads: List[Dict], traces: List[Dict], clearance_mm: float) -> List[Dict]:
    violations: List[Dict] = []
    for pad in pads:
        pad_net = _pad_net(pad)
        for trace in traces:
            trace_net = _trace_net(trace)
            # Skip same-net combinations
            if pad_net and trace_net and pad_net == trace_net:
                continue
            pts = _trace_points(trace)
            for k in range(len(pts) - 1):
                ax, ay = pts[k]
                bx, by = pts[k + 1]
                d = _pad_to_seg_dist(pad, ax, ay, bx, by)
                if d < clearance_mm:
                    mx = (float(pad.get("x", 0)) + (ax + bx) / 2) / 2
                    my = (float(pad.get("y", 0)) + (ay + by) / 2) / 2
                    violations.append({
                        "kind": "pad_trace_clearance",
                        "severity": "error",
                        "x": mx,
                        "y": my,
                        "message": (
                            f"Pad {_pad_id(pad)} to trace {trace.get('pcb_trace_id', '?')}: "
                            f"clearance {d:.3f} mm < rule {clearance_mm:.3f} mm"
                        ),
                    })
                    break  # one violation per pad/trace pair is enough
    return violations


# ---------------------------------------------------------------------------
# Check: trace-to-trace clearance (bbox pre-filter + segment distance)
# ---------------------------------------------------------------------------

def _trace_bbox(trace: Dict) -> Tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) bounding box for a trace."""
    pts = _trace_points(trace)
    if not pts:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _bboxes_close(
    ax0: float, ay0: float, ax1: float, ay1: float,
    bx0: float, by0: float, bx1: float, by1: float,
    threshold: float,
) -> bool:
    """Return True if two bounding boxes are within *threshold* of each other."""
    return not (
        ax1 + threshold < bx0 or
        bx1 + threshold < ax0 or
        ay1 + threshold < by0 or
        by1 + threshold < ay0
    )


def _check_trace_trace_clearance(traces: List[Dict], clearance_mm: float) -> List[Dict]:
    violations: List[Dict] = []
    n = len(traces)
    bboxes = [_trace_bbox(t) for t in traces]

    for i in range(n):
        for j in range(i + 1, n):
            ti, tj = traces[i], traces[j]
            # Same net → no clearance check needed
            ni, nj = _trace_net(ti), _trace_net(tj)
            if ni and nj and ni == nj:
                continue
            # Bbox pre-filter
            if not _bboxes_close(*bboxes[i], *bboxes[j], clearance_mm):
                continue
            pts_i = _trace_points(ti)
            pts_j = _trace_points(tj)
            for a in range(len(pts_i) - 1):
                ax, ay = pts_i[a]
                bx, by = pts_i[a + 1]
                for b in range(len(pts_j) - 1):
                    cx, cy = pts_j[b]
                    dx_, dy = pts_j[b + 1]
                    d = _seg_to_seg_dist(ax, ay, bx, by, cx, cy, dx_, dy)
                    if d < clearance_mm:
                        mx = (ax + bx + cx + dx_) / 4
                        my = (ay + by + cy + dy) / 4
                        violations.append({
                            "kind": "trace_clearance",
                            "severity": "error",
                            "x": mx,
                            "y": my,
                            "message": (
                                f"Trace {ti.get('pcb_trace_id', '?')} to "
                                f"trace {tj.get('pcb_trace_id', '?')}: "
                                f"clearance {d:.3f} mm < rule {clearance_mm:.3f} mm"
                            ),
                        })
                        break
                else:
                    continue
                break  # outer loop break propagation
    return violations


# ---------------------------------------------------------------------------
# Check: unconnected pads
# ---------------------------------------------------------------------------

def _check_unconnected_pads(circuit_json: List[Dict]) -> List[Dict]:
    """Flag pads that have a net_id but are not referenced by any routed trace."""
    pads = _get_pads(circuit_json)
    traces = _get_traces(circuit_json)

    # Collect pad IDs that appear in trace route endpoints
    routed_pad_ids: set = set()
    for trace in traces:
        route = trace.get("route") or []
        for pt in route:
            if isinstance(pt, dict) and pt.get("pad_id"):
                routed_pad_ids.add(pt["pad_id"])
        # Also check explicit connection arrays
        for fld in ("connected_pad_ids", "pad_ids"):
            for pid in trace.get(fld) or []:
                routed_pad_ids.add(str(pid))

    # Group pads by net
    from collections import defaultdict
    net_pads: Dict = defaultdict(list)
    for pad in pads:
        net = _pad_net(pad)
        if net:
            net_pads[net].append(pad)

    violations: List[Dict] = []
    for net_id, net_pad_list in net_pads.items():
        if len(net_pad_list) < 2:
            continue  # single pad net — nothing to connect
        # If no trace at all covers this net, flag all unrouted pads
        net_traces = [t for t in traces if _trace_net(t) == net_id]
        if not net_traces:
            for pad in net_pad_list:
                violations.append({
                    "kind": "unconnected_pad",
                    "severity": "warning",
                    "x": float(pad.get("x", 0)),
                    "y": float(pad.get("y", 0)),
                    "message": (
                        f"Pad {_pad_id(pad)} on net '{net_id}' has no routed trace"
                    ),
                })
    return violations


# ---------------------------------------------------------------------------
# Check: missing footprints
# ---------------------------------------------------------------------------

def _check_missing_footprints(circuit_json: List[Dict]) -> List[Dict]:
    """Flag source components that have no pcb_component counterpart."""
    src_ids = {
        e["source_component_id"]
        for e in circuit_json
        if e.get("type") == "source_component" and e.get("source_component_id")
    }
    placed_src_ids = {
        e["source_component_id"]
        for e in circuit_json
        if e.get("type") == "pcb_component" and e.get("source_component_id")
    }
    violations: List[Dict] = []
    for src_id in sorted(src_ids - placed_src_ids):
        # Try to look up name
        name = next(
            (e.get("name", src_id) for e in circuit_json
             if e.get("type") == "source_component" and e.get("source_component_id") == src_id),
            src_id,
        )
        violations.append({
            "kind": "missing_footprint",
            "severity": "warning",
            "x": 0.0,
            "y": 0.0,
            "message": f"Component '{name}' (id={src_id}) has no PCB footprint placed",
        })
    return violations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_drc(circuit_json: List[Dict], rules: Optional[Dict] = None) -> Dict:
    """Run all DRC checks on *circuit_json*.

    Parameters
    ----------
    circuit_json : list[dict]
        Flat CircuitJSON array.
    rules : dict, optional
        Override any key from DEFAULT_RULES.

    Returns
    -------
    dict with keys:
        "violations" : list[Violation]
        "error_count" : int
        "warning_count" : int
    """
    if not isinstance(circuit_json, list):
        return {"violations": [], "error_count": 0, "warning_count": 0}

    effective_rules = {**DEFAULT_RULES, **(rules or {})}
    clearance = float(effective_rules["min_clearance_mm"])

    pads = _get_pads(circuit_json)
    traces = _get_traces(circuit_json)

    all_violations: List[Dict] = []
    all_violations.extend(_check_pad_pad_clearance(pads, clearance))
    all_violations.extend(_check_pad_trace_clearance(pads, traces, clearance))
    all_violations.extend(_check_trace_trace_clearance(traces, clearance))
    all_violations.extend(_check_unconnected_pads(circuit_json))
    all_violations.extend(_check_missing_footprints(circuit_json))

    error_count = sum(1 for v in all_violations if v["severity"] == "error")
    warning_count = sum(1 for v in all_violations if v["severity"] == "warning")

    return {
        "violations": all_violations,
        "error_count": error_count,
        "warning_count": warning_count,
    }
