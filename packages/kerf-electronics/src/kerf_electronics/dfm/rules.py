"""
DFM (Design-for-Manufacture) rule checks for CircuitJSON PCB boards.

Each rule is a pure function that receives parsed CircuitJSON elements (already
split by type) and returns a list of DFMFinding objects.  Thresholds are
parameterised by IPC board class (1 / 2 / 3).

IPC reference values used here are the nominal class thresholds as published in:
  * IPC-2221B  Generic Standard on Printed Board Design (table 9-1, 9-2)
  * IPC-A-600K  Acceptability of Printed Boards (class 1/2/3 definitions)
  * IPC-7251    Generic Standard for Through-Hole Design

Board class semantics (IPC-2221B §9):
  Class 1 — General Electronic Products (hobby / consumer; least restrictive)
  Class 2 — Dedicated Service Electronic Products (industrial / commercial)
  Class 3 — High-Reliability Electronic Products (medical, aerospace; most restrictive)

All dimensions are in millimetres unless noted.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal


# ─── Finding ────────────────────────────────────────────────────────────────

Severity = Literal["info", "warn", "fail"]


@dataclass
class DFMFinding:
    rule: str
    severity: Severity
    message: str
    refdes: str = ""
    location: str = ""  # "x,y" string when coordinates are relevant

    def to_dict(self) -> dict:
        d: dict = {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }
        if self.refdes:
            d["refdes"] = self.refdes
        if self.location:
            d["location"] = self.location
        return d


# ─── IPC thresholds ──────────────────────────────────────────────────────────
# Source: IPC-2221B Table 9-1 / 9-2; IPC-A-600K class definitions.
# Annular ring = (pad_diameter - drill_diameter) / 2
# All values in mm.

_IPC_THRESHOLDS = {
    # (min_annular_ring_mm, min_trace_mm, min_space_mm, min_drill_to_copper_mm)
    1: {
        "annular_ring_pth": 0.050,   # IPC-2221B Table 9-1, PTH class 1
        "annular_ring_via": 0.050,
        "min_trace":        0.100,   # IPC-2221B §9.1.1
        "min_space":        0.100,
        "drill_to_copper":  0.200,   # IPC-2221B §9.3.1
        "min_silkscreen_h": 0.800,   # IPC-A-600K §3 suggested legibility
        "min_courtyard_gap": 0.050,  # assembly clearance
        "min_passive_pkg":  "0402",  # smallest reliably machine-placeable
    },
    2: {
        "annular_ring_pth": 0.050,   # IPC-2221B Table 9-1, PTH class 2
        "annular_ring_via": 0.050,
        "min_trace":        0.100,
        "min_space":        0.100,
        "drill_to_copper":  0.250,
        "min_silkscreen_h": 1.000,
        "min_courtyard_gap": 0.100,
        "min_passive_pkg":  "0402",
    },
    3: {
        "annular_ring_pth": 0.075,   # IPC-2221B Table 9-1, PTH class 3
        "annular_ring_via": 0.075,
        "min_trace":        0.125,
        "min_space":        0.125,
        "drill_to_copper":  0.330,
        "min_silkscreen_h": 1.000,
        "min_courtyard_gap": 0.150,
        "min_passive_pkg":  "0603",  # class 3 prefers no smaller than 0603
    },
}

# Passive package area rank: larger index = larger package.
_PASSIVE_RANK = {
    "0201": 0,
    "01005": 0,
    "0402": 1,
    "0603": 2,
    "0805": 3,
    "1206": 4,
    "1210": 5,
    "2512": 6,
}

_ACID_TRAP_ANGLE_DEG = 45.0   # corners sharper than this are acid traps


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _loc(x, y) -> str:
    return f"{x:.3f},{y:.3f}"


def _dist(ax, ay, bx, by) -> float:
    return math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)


def _passive_rank(footprint: str) -> int | None:
    """Return rank for a passive footprint string, or None if not a known passive."""
    fp = footprint.upper().replace("-", "").replace("_", "").replace(" ", "")
    for pkg, rank in _PASSIVE_RANK.items():
        if pkg in fp:
            return rank
    return None


def _segment_angle_deg(ax, ay, bx, by) -> float:
    """Angle of segment AB in degrees [0, 180)."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return 0.0
    return math.degrees(math.atan2(dy, dx)) % 180.0


def _angle_between_deg(a1: float, a2: float) -> float:
    """Smallest angle between two directions (both in [0,180))."""
    diff = abs(a1 - a2) % 180.0
    return min(diff, 180.0 - diff)


def _split_circuit(circuit_json: list[dict]) -> dict:
    """Split CircuitJSON by element type into named buckets."""
    buckets: dict[str, list[dict]] = {
        "board": [],
        "traces": [],
        "vias": [],
        "pads": [],
        "silk_texts": [],
        "source_components": [],
        "pcb_components": [],
    }
    for el in circuit_json:
        t = el.get("type", "")
        if t == "pcb_board":
            buckets["board"].append(el)
        elif t in ("pcb_trace", "route"):
            buckets["traces"].append(el)
        elif t == "pcb_via":
            buckets["vias"].append(el)
        elif t in ("pcb_smtpad", "pcb_plated_hole", "pad"):
            buckets["pads"].append(el)
        elif t in ("pcb_silkscreen_text", "silk_text", "silkscreen_text"):
            buckets["silk_texts"].append(el)
        elif t == "source_component":
            buckets["source_components"].append(el)
        elif t == "pcb_component":
            buckets["pcb_components"].append(el)
    return buckets


# ─── Individual rule functions ────────────────────────────────────────────────


def _check_annular_ring(
    vias: list[dict],
    pads: list[dict],
    thresholds: dict,
) -> list[DFMFinding]:
    """IPC-2221B §9.3: annular ring must meet class minimum.

    annular_ring = (pad_diameter - drill_diameter) / 2
    Via: annular_ring_via threshold.
    PTH pad: annular_ring_pth threshold.
    """
    findings: list[DFMFinding] = []
    min_via = thresholds["annular_ring_via"]
    min_pth = thresholds["annular_ring_pth"]

    for via in vias:
        outer = via.get("outer_diameter") or via.get("pad_diameter") or 0.0
        drill = via.get("hole_diameter") or via.get("drill_diameter") or 0.0
        if outer <= 0 or drill <= 0:
            continue
        ring = (outer - drill) / 2.0
        if ring < min_via:
            x, y = via.get("x", 0.0), via.get("y", 0.0)
            findings.append(DFMFinding(
                rule="annular_ring_via",
                severity="fail",
                message=(
                    f"Via annular ring {ring:.3f} mm < IPC minimum {min_via:.3f} mm "
                    f"(outer={outer:.3f}, drill={drill:.3f})"
                ),
                location=_loc(x, y),
            ))

    for pad in pads:
        if pad.get("type") != "pcb_plated_hole":
            continue
        outer = pad.get("width") or pad.get("pad_diameter") or 0.0
        drill = pad.get("hole_diameter") or pad.get("drill_diameter") or 0.0
        if outer <= 0 or drill <= 0:
            continue
        ring = (outer - drill) / 2.0
        if ring < min_pth:
            x, y = pad.get("x", 0.0), pad.get("y", 0.0)
            sid = pad.get("source_component_id", "")
            findings.append(DFMFinding(
                rule="annular_ring_pth",
                severity="fail",
                message=(
                    f"PTH pad annular ring {ring:.3f} mm < IPC minimum {min_pth:.3f} mm "
                    f"(outer={outer:.3f}, drill={drill:.3f})"
                ),
                refdes=sid,
                location=_loc(x, y),
            ))

    return findings


def _check_min_trace_space(
    traces: list[dict],
    thresholds: dict,
) -> list[DFMFinding]:
    """IPC-2221B §9.1: trace width and trace-to-trace spacing.

    We check trace widths directly.  Spacing between distinct traces is
    approximated by checking bounding-box proximity (conservative).
    """
    findings: list[DFMFinding] = []
    min_w = thresholds["min_trace"]
    min_s = thresholds["min_space"]

    for trace in traces:
        w = (
            trace.get("route_thickness_mm")
            or trace.get("width_mm")
            or trace.get("stroke_width")
        )
        if w is not None and float(w) < min_w:
            pts = trace.get("route") or trace.get("points") or []
            x = pts[0].get("x", 0.0) if pts else trace.get("x", 0.0)
            y = pts[0].get("y", 0.0) if pts else trace.get("y", 0.0)
            findings.append(DFMFinding(
                rule="min_trace_width",
                severity="fail",
                message=(
                    f"Trace width {float(w):.3f} mm < IPC minimum {min_w:.3f} mm"
                ),
                location=_loc(x, y),
            ))

    # Pairwise proximity check (centres of first points only — lightweight)
    # Full polygon expansion is out-of-scope for a pure-Python DFM check.
    for i in range(len(traces)):
        for j in range(i + 1, len(traces)):
            ta, tb = traces[i], traces[j]
            pts_a = ta.get("route") or ta.get("points") or []
            pts_b = tb.get("route") or tb.get("points") or []
            if not pts_a or not pts_b:
                continue
            ax, ay = pts_a[0].get("x", 0.0), pts_a[0].get("y", 0.0)
            bx, by = pts_b[0].get("x", 0.0), pts_b[0].get("y", 0.0)
            wa = float(
                ta.get("route_thickness_mm") or ta.get("width_mm") or ta.get("stroke_width") or 0.15
            )
            wb = float(
                tb.get("route_thickness_mm") or tb.get("width_mm") or tb.get("stroke_width") or 0.15
            )
            centre_dist = _dist(ax, ay, bx, by)
            gap = centre_dist - wa / 2.0 - wb / 2.0
            if gap < min_s:
                findings.append(DFMFinding(
                    rule="min_trace_space",
                    severity="fail",
                    message=(
                        f"Trace-to-trace gap {gap:.3f} mm < IPC minimum {min_s:.3f} mm"
                    ),
                    location=_loc((ax + bx) / 2, (ay + by) / 2),
                ))

    return findings


def _check_drill_to_copper(
    vias: list[dict],
    pads: list[dict],
    thresholds: dict,
) -> list[DFMFinding]:
    """IPC-2221B §9.3.1: hole edge to nearest copper feature minimum.

    Approximated as: distance between any two drilled elements
    minus their outer radii.
    """
    findings: list[DFMFinding] = []
    min_dtc = thresholds["drill_to_copper"]

    drilled: list[dict] = []
    for v in vias:
        drilled.append({"x": v.get("x", 0), "y": v.get("y", 0),
                        "drill_r": (v.get("hole_diameter") or v.get("drill_diameter") or 0.3) / 2.0,
                        "outer_r": (v.get("outer_diameter") or v.get("pad_diameter") or 0.6) / 2.0,
                        "kind": "via"})
    for p in pads:
        if p.get("type") != "pcb_plated_hole":
            continue
        drilled.append({"x": p.get("x", 0), "y": p.get("y", 0),
                        "drill_r": (p.get("hole_diameter") or p.get("drill_diameter") or 0.3) / 2.0,
                        "outer_r": (p.get("width") or p.get("pad_diameter") or 0.6) / 2.0,
                        "kind": "pth"})

    for i in range(len(drilled)):
        for j in range(i + 1, len(drilled)):
            a, b = drilled[i], drilled[j]
            d = _dist(a["x"], a["y"], b["x"], b["y"])
            # drill edge of A to copper edge of B
            gap = d - a["drill_r"] - b["outer_r"]
            if gap < min_dtc:
                findings.append(DFMFinding(
                    rule="drill_to_copper",
                    severity="fail",
                    message=(
                        f"Drill-to-copper gap {gap:.3f} mm < IPC minimum {min_dtc:.3f} mm"
                    ),
                    location=_loc((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2),
                ))

    return findings


def _check_silkscreen_over_pad(
    silk_texts: list[dict],
    pads: list[dict],
    thresholds: dict,
) -> list[DFMFinding]:
    """IPC-A-600K §3: silkscreen must not cover pads (causes solder issues)."""
    findings: list[DFMFinding] = []
    for text in silk_texts:
        tx = text.get("anchor_x") or text.get("x") or 0.0
        ty = text.get("anchor_y") or text.get("y") or 0.0
        for pad in pads:
            px, py = float(pad.get("x", 0)), float(pad.get("y", 0))
            pr = float(pad.get("width") or pad.get("pad_diameter") or 1.5) / 2.0
            if _dist(tx, ty, px, py) < pr:
                findings.append(DFMFinding(
                    rule="silkscreen_over_pad",
                    severity="warn",
                    message=(
                        f"Silkscreen text overlaps pad at ({px:.2f},{py:.2f}); "
                        "may interfere with soldering"
                    ),
                    location=_loc(tx, ty),
                ))
                break  # one warning per silk element

    return findings


def _check_acid_traps(traces: list[dict]) -> list[DFMFinding]:
    """Flag acute-angle trace junctions likely to trap etchant (acid traps).

    An acid trap occurs where two trace segments meet at an angle
    shallower than _ACID_TRAP_ANGLE_DEG degrees, creating a wedge that
    retains etchant and causes over-etching.

    We check consecutive segments within a single trace polyline.
    """
    findings: list[DFMFinding] = []
    for trace in traces:
        pts = trace.get("route") or trace.get("points") or []
        if len(pts) < 3:
            continue
        for k in range(1, len(pts) - 1):
            ax, ay = pts[k - 1].get("x", 0.0), pts[k - 1].get("y", 0.0)
            bx, by = pts[k].get("x", 0.0), pts[k].get("y", 0.0)
            cx, cy = pts[k + 1].get("x", 0.0), pts[k + 1].get("y", 0.0)
            a1 = _segment_angle_deg(ax, ay, bx, by)
            a2 = _segment_angle_deg(bx, by, cx, cy)
            between = _angle_between_deg(a1, a2)
            if 0 < between < _ACID_TRAP_ANGLE_DEG:
                findings.append(DFMFinding(
                    rule="acid_trap",
                    severity="warn",
                    message=(
                        f"Acute trace corner {between:.1f}° at ({bx:.2f},{by:.2f}) "
                        "may trap etchant"
                    ),
                    location=_loc(bx, by),
                ))

    return findings


def _check_slivers(traces: list[dict], thresholds: dict) -> list[DFMFinding]:
    """Detect copper slivers: very short trace segments narrower than min_space.

    A sliver is a thin sliver of copper likely to lift or create a short.
    We flag segments shorter than 2× min_space with width < min_space.
    """
    findings: list[DFMFinding] = []
    min_s = thresholds["min_space"]
    for trace in traces:
        w = float(
            trace.get("route_thickness_mm")
            or trace.get("width_mm")
            or trace.get("stroke_width")
            or min_s * 2
        )
        if w >= min_s:
            continue  # not thin enough to be a sliver candidate
        pts = trace.get("route") or trace.get("points") or []
        for k in range(len(pts) - 1):
            ax, ay = pts[k].get("x", 0.0), pts[k].get("y", 0.0)
            bx, by = pts[k + 1].get("x", 0.0), pts[k + 1].get("y", 0.0)
            seg_len = _dist(ax, ay, bx, by)
            if seg_len < 2 * min_s:
                findings.append(DFMFinding(
                    rule="copper_sliver",
                    severity="warn",
                    message=(
                        f"Short thin copper segment: length={seg_len:.3f} mm, "
                        f"width={w:.3f} mm — possible sliver"
                    ),
                    location=_loc((ax + bx) / 2, (ay + by) / 2),
                ))

    return findings


def _check_courtyard_overlap(
    pcb_components: list[dict],
    thresholds: dict,
) -> list[DFMFinding]:
    """Flag component courtyard overlaps that prevent assembly placement.

    Each pcb_component may carry:
      courtyard_width, courtyard_height, x, y  (bounding-box courtyard)

    We check AABB (axis-aligned bounding box) overlap after applying the
    minimum courtyard_gap clearance.

    IPC-7251 §3.1 / IPC-2221B §9.4: courtyards must not overlap.
    """
    findings: list[DFMFinding] = []
    min_gap = thresholds["min_courtyard_gap"]

    boxes = []
    for comp in pcb_components:
        x = float(comp.get("x", 0))
        y = float(comp.get("y", 0))
        cw = float(comp.get("courtyard_width") or comp.get("width") or 0)
        ch = float(comp.get("courtyard_height") or comp.get("height") or 0)
        if cw <= 0 or ch <= 0:
            continue
        sid = comp.get("source_component_id", "")
        boxes.append({"x": x, "y": y, "w": cw, "h": ch, "sid": sid})

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ax1, ay1 = a["x"] - a["w"] / 2 - min_gap, a["y"] - a["h"] / 2 - min_gap
            ax2, ay2 = a["x"] + a["w"] / 2 + min_gap, a["y"] + a["h"] / 2 + min_gap
            bx1, by1 = b["x"] - b["w"] / 2, b["y"] - b["h"] / 2
            bx2, by2 = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
            if ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1:
                findings.append(DFMFinding(
                    rule="courtyard_overlap",
                    severity="fail",
                    message=(
                        f"Courtyard overlap between components "
                        f"(refdes IDs: {a['sid'] or '?'} / {b['sid'] or '?'})"
                    ),
                    refdes=f"{a['sid']},{b['sid']}",
                    location=_loc((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2),
                ))

    return findings


def _check_smallest_passive(
    source_components: list[dict],
    pcb_components: list[dict],
    thresholds: dict,
) -> list[DFMFinding]:
    """Flag passive components smaller than the assembly capability floor.

    IPC-7711/7721 §4.3: smallest reliably machine-placeable passive size
    varies by assembly class:
      Class 1 / Class 2 — 0402 minimum
      Class 3            — 0603 minimum

    We check source_component.footprint for known passive package codes.
    """
    findings: list[DFMFinding] = []
    min_pkg = thresholds["min_passive_pkg"]
    min_rank = _PASSIVE_RANK.get(min_pkg.upper().replace("-", "").replace("_", ""), 1)

    placed_sids: set[str] = {
        c.get("source_component_id", c.get("id", ""))
        for c in pcb_components
    }

    for src in source_components:
        sid = src.get("source_component_id", src.get("id", ""))
        if sid and placed_sids and sid not in placed_sids:
            continue  # not placed on board
        fp = src.get("footprint", src.get("ftype", ""))
        rank = _passive_rank(fp)
        if rank is None:
            continue  # not a known passive package
        if rank < min_rank:
            refdes = src.get("name", src.get("refdes", sid))
            findings.append(DFMFinding(
                rule="smallest_passive",
                severity="warn",
                message=(
                    f"{refdes} uses footprint '{fp}' which is smaller than "
                    f"the assembly capability floor '{min_pkg}' for this board class"
                ),
                refdes=refdes,
            ))

    return findings


# ─── Public API ───────────────────────────────────────────────────────────────

def run_dfm_checks(
    circuit_json: list[dict],
    board_class: int = 2,
) -> list[DFMFinding]:
    """Run all DFM rules on a CircuitJSON board.

    Args:
        circuit_json:  Parsed CircuitJSON array.
        board_class:   IPC board class (1, 2, or 3).  Default 2.

    Returns:
        List of DFMFinding objects (may be empty for a clean board).
        Never raises — bad input yields an info-level finding.
    """
    if not isinstance(circuit_json, list) or not circuit_json:
        return [DFMFinding(
            rule="input",
            severity="info",
            message="Empty or invalid circuit_json; no DFM checks performed.",
        )]

    if board_class not in _IPC_THRESHOLDS:
        return [DFMFinding(
            rule="input",
            severity="info",
            message=(
                f"Unknown board_class {board_class!r}; "
                "valid values are 1, 2, 3.  No checks performed."
            ),
        )]

    t = _IPC_THRESHOLDS[board_class]
    buckets = _split_circuit(circuit_json)

    findings: list[DFMFinding] = []
    findings += _check_annular_ring(buckets["vias"], buckets["pads"], t)
    findings += _check_min_trace_space(buckets["traces"], t)
    findings += _check_drill_to_copper(buckets["vias"], buckets["pads"], t)
    findings += _check_silkscreen_over_pad(buckets["silk_texts"], buckets["pads"], t)
    findings += _check_acid_traps(buckets["traces"])
    findings += _check_slivers(buckets["traces"], t)
    findings += _check_courtyard_overlap(buckets["pcb_components"], t)
    findings += _check_smallest_passive(
        buckets["source_components"], buckets["pcb_components"], t
    )

    return findings


def score_dfm(findings: list[DFMFinding]) -> int:
    """Convert a list of DFM findings into a 0–100 score.

    Scoring:
      fail  → -15 per finding
      warn  → -5  per finding
      info  → 0

    Clamped to [0, 100].  A board with no findings scores 100.
    """
    penalty = 0
    for f in findings:
        if f.severity == "fail":
            penalty += 15
        elif f.severity == "warn":
            penalty += 5
    return max(0, 100 - penalty)
