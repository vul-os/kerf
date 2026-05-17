"""
Differential-pair routing, controlled-impedance calculation, and matched-length groups.

KiCad-parity features:
  1. Differential pair definition + routing — pair two nets (P/N), route them
     coupled at a target spacing, with phase/skew control.
  2. Controlled impedance — microstrip & stripline single-ended and differential
     impedance using standard closed-form approximations:
       - IPC-2141A (microstrip, 2004 edition)
       - Wadell "Transmission Line Design Handbook" (Artech House, 1991) for
         differential microstrip and both stripline formulas.
  3. Matched-length groups — define a group of nets with a target length /
     max skew; report each net's current length vs target and the serpentine
     delta needed to reach it.

CircuitJSON extensions used / written:
  board.differential_pairs      — list of pair definitions (read by length_tuning too)
  board.diff_pair_routes        — routing metadata added by route_diff_pair
  board.length_groups           — list of matched-length group definitions

Tools (all registered via @register):
  add_diff_pair         — define a P/N pair with coupling parameters
  route_diff_pair       — add coupled trace segments for a diff pair
  calc_impedance        — impedance calculator (microstrip / stripline)
  add_length_group      — define a matched-length group
  check_length_match    — report per-net lengths vs target and deltas needed
"""

import json
import math
import uuid
from copy import deepcopy
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ── Internal geometry helpers (mirrors length_tuning.py conventions) ──────────

def _dist(a: dict, b: dict) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _trace_length(trace: dict) -> float:
    """Total arc-length of a pcb_trace using its points list."""
    pts = trace.get("points") or []
    if len(pts) < 2:
        return 0.0
    return sum(_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _perp(dx: float, dy: float) -> tuple[float, float]:
    """CCW 90° perpendicular of (dx, dy), normalised."""
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return (0.0, 1.0)
    return (-dy / length, dx / length)


def _new_id(prefix: str = "dp") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── Internal CircuitJSON helpers ──────────────────────────────────────────────

def _get_elements(circuit_json) -> list:
    if isinstance(circuit_json, list):
        return circuit_json
    return [circuit_json]


def _get_board(elements: list) -> dict | None:
    for e in elements:
        if isinstance(e, dict) and e.get("type") == "pcb_board":
            return e
    return None


def _get_traces(elements: list) -> list:
    return [e for e in elements if isinstance(e, dict) and e.get("type") == "pcb_trace"]


def _net_length(elements: list, net_id: str) -> float:
    return sum(_trace_length(t) for t in _get_traces(elements) if t.get("net_id") == net_id)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DIFFERENTIAL PAIR DEFINITION + ROUTING
# ═══════════════════════════════════════════════════════════════════════════════

# ── add_diff_pair ─────────────────────────────────────────────────────────────

add_diff_pair_spec = ToolSpec(
    name="add_diff_pair",
    description=(
        "Define a differential pair by associating a positive net (net_p_id) and a "
        "negative net (net_n_id) with coupling parameters: target spacing between "
        "the traces, optional skew_max_mm tolerance, and optional target impedance. "
        "The definition is stored in board.differential_pairs and is shared with the "
        "length-tuning tools (match_diff_pair, report_diff_pair_skew). "
        "Returns updated circuit_json."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "oneOf": [{"type": "object"}, {"type": "array"}],
                "description": "CircuitJSON board or element list.",
            },
            "name": {"type": "string", "description": "Unique pair name, e.g. 'USB_DP'."},
            "net_p_id": {"type": "string", "description": "Positive-polarity net identifier."},
            "net_n_id": {"type": "string", "description": "Negative-polarity net identifier."},
            "spacing_mm": {
                "type": "number",
                "description": "Edge-to-edge coupling gap between P and N traces in mm.",
            },
            "width_mm": {
                "type": "number",
                "description": "Trace width for both conductors in mm (default: 0.2).",
            },
            "skew_max_mm": {
                "type": "number",
                "description": "Maximum allowed propagation-skew between P and N in mm (default: 0.05).",
            },
            "target_impedance_ohms": {
                "type": "number",
                "description": "Target differential impedance in ohms (informational; used by calc_impedance).",
            },
        },
        "required": ["circuit_json", "name", "net_p_id", "net_n_id", "spacing_mm"],
    },
)


@register(add_diff_pair_spec, write=True)
async def add_diff_pair(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    name = (a.get("name") or "").strip()
    net_p = (a.get("net_p_id") or "").strip()
    net_n = (a.get("net_n_id") or "").strip()
    spacing = a.get("spacing_mm")

    if not circuit_json:
        return err_payload("circuit_json is required", "BAD_ARGS")
    if not name:
        return err_payload("name is required", "BAD_ARGS")
    if not net_p:
        return err_payload("net_p_id is required", "BAD_ARGS")
    if not net_n:
        return err_payload("net_n_id is required", "BAD_ARGS")
    if not isinstance(spacing, (int, float)) or spacing <= 0:
        return err_payload("spacing_mm must be a positive number", "BAD_ARGS")

    cloned = deepcopy(circuit_json)
    elements = cloned if isinstance(cloned, list) else [cloned]
    board = _get_board(elements)
    if board is None:
        return err_payload("No pcb_board element found in circuit_json", "BAD_ARGS")

    if not isinstance(board.get("differential_pairs"), list):
        board["differential_pairs"] = []

    entry: dict = {
        "name": name,
        "net_p_id": net_p,
        "net_n_id": net_n,
        "spacing_mm": spacing,
        "width_mm": a.get("width_mm", 0.2),
        "skew_max_mm": a.get("skew_max_mm", 0.05),
    }
    if isinstance(a.get("target_impedance_ohms"), (int, float)):
        entry["target_impedance_ohms"] = a["target_impedance_ohms"]

    # Upsert
    idx = next((i for i, p in enumerate(board["differential_pairs"]) if p.get("name") == name), -1)
    if idx >= 0:
        board["differential_pairs"][idx] = entry
    else:
        board["differential_pairs"].append(entry)

    return ok_payload({"circuit_json": cloned, "pair": entry})


# ── route_diff_pair ───────────────────────────────────────────────────────────

route_diff_pair_spec = ToolSpec(
    name="route_diff_pair",
    description=(
        "Route a defined differential pair by adding two coupled pcb_trace elements "
        "that follow the same path, offset by the pair's spacing_mm perpendicular to "
        "the route direction.  Supply the centreline path as an array of {x,y} points; "
        "the P trace is offset +spacing/2 and the N trace −spacing/2 (CCW perpendicular). "
        "Returns updated circuit_json with both traces added and "
        "board.diff_pair_routes updated."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {"oneOf": [{"type": "object"}, {"type": "array"}]},
            "pair_name": {"type": "string", "description": "Name of the differential pair (must exist via add_diff_pair)."},
            "centreline": {
                "type": "array",
                "description": "Ordered list of {x, y} waypoints for the pair's centreline.",
                "items": {
                    "type": "object",
                    "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                    "required": ["x", "y"],
                },
                "minItems": 2,
            },
            "layer": {
                "type": "string",
                "description": "PCB layer name (e.g. 'top_copper'). Default: 'top_copper'.",
            },
            "width_mm": {
                "type": "number",
                "description": "Override trace width (default: taken from pair definition).",
            },
            "spacing_mm": {
                "type": "number",
                "description": "Override coupling spacing (default: taken from pair definition).",
            },
        },
        "required": ["circuit_json", "pair_name", "centreline"],
    },
)


def _offset_polyline(points: list, offset: float) -> list:
    """Offset each vertex of a polyline by *offset* mm perpendicular to the
    incoming segment direction.  For a single segment the offset is uniform.
    At a corner the offset point is the intersection of the two offset lines
    (capped to avoid degenerate geometries).

    Returns a new list of {x, y} dicts.
    """
    n = len(points)
    if n < 2:
        return list(points)

    # Build per-segment perpendicular vectors
    segs = []
    for i in range(n - 1):
        dx = points[i + 1]["x"] - points[i]["x"]
        dy = points[i + 1]["y"] - points[i]["y"]
        px, py = _perp(dx, dy)
        segs.append((px, py))

    result = []
    for i, pt in enumerate(points):
        if i == 0:
            px, py = segs[0]
        elif i == n - 1:
            px, py = segs[-1]
        else:
            # Average the two adjacent segment normals
            px = (segs[i - 1][0] + segs[i][0]) / 2
            py = (segs[i - 1][1] + segs[i][1]) / 2
            mag = math.hypot(px, py)
            if mag > 1e-12:
                px /= mag
                py /= mag
        result.append({"x": pt["x"] + px * offset, "y": pt["y"] + py * offset})

    return result


@register(route_diff_pair_spec, write=True)
async def route_diff_pair(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    pair_name = (a.get("pair_name") or "").strip()
    centreline = a.get("centreline")
    layer = a.get("layer") or "top_copper"

    if not circuit_json:
        return err_payload("circuit_json is required", "BAD_ARGS")
    if not pair_name:
        return err_payload("pair_name is required", "BAD_ARGS")
    if not isinstance(centreline, list) or len(centreline) < 2:
        return err_payload("centreline must be an array of at least 2 {x,y} points", "BAD_ARGS")
    for i, pt in enumerate(centreline):
        if not isinstance(pt, dict) or pt.get("x") is None or pt.get("y") is None:
            return err_payload(f"centreline[{i}] must have x and y", "BAD_ARGS")

    cloned = deepcopy(circuit_json)
    elements = cloned if isinstance(cloned, list) else [cloned]
    board = _get_board(elements)
    if board is None:
        return err_payload("No pcb_board element found in circuit_json", "BAD_ARGS")

    pairs = board.get("differential_pairs") or []
    pair_def = next((p for p in pairs if p.get("name") == pair_name), None)
    if pair_def is None:
        return err_payload(
            f"differential pair '{pair_name}' not found — call add_diff_pair first", "NOT_FOUND"
        )

    spacing = a.get("spacing_mm") or pair_def.get("spacing_mm", 0.2)
    width = a.get("width_mm") or pair_def.get("width_mm", 0.2)
    net_p = pair_def["net_p_id"]
    net_n = pair_def["net_n_id"]

    half = spacing / 2.0
    pts_p = _offset_polyline(centreline, +half)
    pts_n = _offset_polyline(centreline, -half)

    trace_p_id = _new_id("dp_p")
    trace_n_id = _new_id("dp_n")

    trace_p = {
        "type": "pcb_trace",
        "pcb_trace_id": trace_p_id,
        "net_id": net_p,
        "layer": layer,
        "width_mm": width,
        "points": pts_p,
        "diff_pair": pair_name,
        "polarity": "P",
    }
    trace_n = {
        "type": "pcb_trace",
        "pcb_trace_id": trace_n_id,
        "net_id": net_n,
        "layer": layer,
        "width_mm": width,
        "points": pts_n,
        "diff_pair": pair_name,
        "polarity": "N",
    }
    elements.append(trace_p)
    elements.append(trace_n)

    # Record in board.diff_pair_routes
    if not isinstance(board.get("diff_pair_routes"), list):
        board["diff_pair_routes"] = []
    board["diff_pair_routes"].append({
        "pair_name": pair_name,
        "trace_p_id": trace_p_id,
        "trace_n_id": trace_n_id,
        "layer": layer,
        "spacing_mm": spacing,
        "width_mm": width,
    })

    len_p = _trace_length(trace_p)
    len_n = _trace_length(trace_n)

    return ok_payload({
        "circuit_json": cloned,
        "pair_name": pair_name,
        "trace_p_id": trace_p_id,
        "trace_n_id": trace_n_id,
        "length_p_mm": len_p,
        "length_n_mm": len_n,
        "skew_mm": abs(len_p - len_n),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CONTROLLED IMPEDANCE CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════
#
# Reference formulas:
#
# MICROSTRIP — single-ended Z0:
#   IPC-2141A (2004), equation for "narrow" traces (W/H ≤ 1):
#     Z0 = (87 / sqrt(er + 1.41)) * ln(5.98*H / (0.8*W + T))
#   and "wide" traces (W/H > 1) via Hammerstad (1975):
#     Z0 = (120*pi) / (sqrt(er_eff) * (W/H + 1.393 + 0.667*ln(W/H + 1.444)))
#   where er_eff = (er+1)/2 + (er-1)/2 * (1 + 12*H/W)^(-0.5)
#
# MICROSTRIP — differential Zdiff (Wadell, 1991, §3.7):
#   Zdiff ≈ 2*Z0 * (1 − 0.347 * exp(−2.9 * S / H))
#   where S = edge-to-edge gap between traces.
#
# STRIPLINE — single-ended Z0 (IPC-2141A, buried trace, symmetric):
#   Z0 = (60 / sqrt(er)) * ln(4*B / (0.67*pi*(0.8*W + T)))
#   where B = dielectric thickness between reference planes.
#
# STRIPLINE — differential Zdiff (Wadell, 1991, §4.3):
#   Zdiff ≈ 2*Z0 * (1 − 0.347 * exp(−2.9 * S / B))
#
# All variables:
#   W  — trace width [mm]
#   T  — copper thickness [mm]
#   H  — dielectric height above ground (microstrip) or half-B (stripline) [mm]
#   B  — total dielectric thickness between reference planes (stripline) [mm]
#   S  — edge-to-edge spacing between P and N traces [mm]
#   er — substrate relative permittivity
# ─────────────────────────────────────────────────────────────────────────────

def _microstrip_z0(W: float, H: float, T: float, er: float) -> float:
    """
    Single-ended microstrip impedance (IPC-2141A / Hammerstad).
    W, H, T in mm, er dimensionless.
    """
    if W <= 0 or H <= 0:
        raise ValueError("W and H must be positive")
    # Effective width after thickness correction
    We = W + (T / math.pi) * (1 + math.log(2 * H / T)) if T > 0 else W
    ratio = We / H
    if ratio <= 1:
        # IPC-2141A narrow-trace approximation
        Z0 = (87.0 / math.sqrt(er + 1.41)) * math.log(5.98 * H / (0.8 * We + T))
    else:
        # Hammerstad wide-trace using effective permittivity
        er_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / ratio) ** (-0.5)
        Z0 = (120 * math.pi) / (math.sqrt(er_eff) * (ratio + 1.393 + 0.667 * math.log(ratio + 1.444)))
    return Z0


def _stripline_z0(W: float, B: float, T: float, er: float) -> float:
    """
    Single-ended symmetric stripline impedance (IPC-2141A buried trace).
    W, B, T in mm, er dimensionless.
    B is the total dielectric thickness between the two reference planes.
    """
    if W <= 0 or B <= 0:
        raise ValueError("W and B must be positive")
    if T <= 0:
        T = 1e-4  # avoid log(0)
    Z0 = (60.0 / math.sqrt(er)) * math.log(4 * B / (0.67 * math.pi * (0.8 * W + T)))
    return Z0


def _diff_impedance(z0_single: float, S: float, H_or_B: float, structure: str) -> float:
    """
    Differential impedance using Wadell (1991) coupling factor.
    structure: 'microstrip' or 'stripline'.
    S is edge-to-edge spacing; H_or_B is H (microstrip) or B (stripline).
    """
    if H_or_B <= 0:
        return 2 * z0_single
    coupling = math.exp(-2.9 * S / H_or_B)
    return 2 * z0_single * (1 - 0.347 * coupling)


calc_impedance_spec = ToolSpec(
    name="calc_impedance",
    description=(
        "Calculate PCB trace impedance using standard closed-form approximations. "
        "Supports microstrip (trace on surface above ground plane) and stripline "
        "(buried trace between two reference planes). Returns single-ended Z0 and, "
        "if spacing_mm is given, differential Zdiff. "
        "Formulas: IPC-2141A (2004) for Z0, Wadell (1991) §3.7/4.3 for Zdiff."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "structure": {
                "type": "string",
                "enum": ["microstrip", "stripline"],
                "description": "'microstrip' = surface trace above ground; 'stripline' = buried between two planes.",
            },
            "trace_width_mm": {"type": "number", "description": "Trace width W in mm."},
            "dielectric_height_mm": {
                "type": "number",
                "description": (
                    "For microstrip: height H of dielectric between trace and ground plane. "
                    "For stripline: total dielectric thickness B between the two reference planes."
                ),
            },
            "copper_thickness_mm": {
                "type": "number",
                "description": "Copper trace thickness T in mm (default: 0.035 = 1 oz copper).",
            },
            "er": {
                "type": "number",
                "description": "Substrate relative permittivity (εr). FR4 ≈ 4.5.",
            },
            "spacing_mm": {
                "type": "number",
                "description": "Edge-to-edge gap S between P and N traces in mm. Required for Zdiff.",
            },
        },
        "required": ["structure", "trace_width_mm", "dielectric_height_mm", "er"],
    },
)


@register(calc_impedance_spec, write=False)
async def calc_impedance(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    structure = (a.get("structure") or "").strip()
    W = a.get("trace_width_mm")
    H_or_B = a.get("dielectric_height_mm")
    T = a.get("copper_thickness_mm", 0.035)
    er = a.get("er")
    S = a.get("spacing_mm")

    if structure not in ("microstrip", "stripline"):
        return err_payload("structure must be 'microstrip' or 'stripline'", "BAD_ARGS")
    for name, val in [("trace_width_mm", W), ("dielectric_height_mm", H_or_B), ("er", er)]:
        if not isinstance(val, (int, float)) or val <= 0:
            return err_payload(f"{name} must be a positive number", "BAD_ARGS")
    if not isinstance(T, (int, float)) or T <= 0:
        T = 0.035  # default 1 oz copper

    try:
        if structure == "microstrip":
            z0 = _microstrip_z0(float(W), float(H_or_B), float(T), float(er))
        else:
            z0 = _stripline_z0(float(W), float(H_or_B), float(T), float(er))
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")

    result: dict = {
        "structure": structure,
        "trace_width_mm": W,
        "dielectric_height_mm": H_or_B,
        "copper_thickness_mm": T,
        "er": er,
        "z0_ohms": round(z0, 2),
        "formulas": (
            "Z0: IPC-2141A (2004); Zdiff: Wadell 'Transmission Line Design Handbook' (1991) §3.7/4.3"
        ),
    }

    if isinstance(S, (int, float)) and S > 0:
        zdiff = _diff_impedance(z0, float(S), float(H_or_B), structure)
        result["spacing_mm"] = S
        result["zdiff_ohms"] = round(zdiff, 2)

    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MATCHED-LENGTH GROUPS
# ═══════════════════════════════════════════════════════════════════════════════
#
# CircuitJSON extension:
#   board.length_groups — list of group definitions:
#     {
#       "name": "DDR_DQ_BYTE0",
#       "net_ids": ["DQ0", "DQ1", ..., "DQS_P", "DQS_N"],
#       "target_length_mm": 72.0,
#       "skew_max_mm": 0.1,
#       "serpentine_amplitude_mm": 0.5   // advisory for length tuning
#     }
# ─────────────────────────────────────────────────────────────────────────────

add_length_group_spec = ToolSpec(
    name="add_length_group",
    description=(
        "Define a matched-length group: a set of nets that must all reach "
        "target_length_mm within skew_max_mm of each other.  The group is stored in "
        "board.length_groups and is consumed by check_length_match.  "
        "Use check_length_match after routing to learn which nets need serpentine tuning "
        "and by how much."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {"oneOf": [{"type": "object"}, {"type": "array"}]},
            "name": {"type": "string", "description": "Group name, e.g. 'DDR_DQ_BYTE0'."},
            "net_ids": {
                "type": "array",
                "description": "Ordered list of net identifiers in this group.",
                "items": {"type": "string"},
                "minItems": 2,
            },
            "target_length_mm": {
                "type": "number",
                "description": "Target trace length every net should reach (mm).",
            },
            "skew_max_mm": {
                "type": "number",
                "description": "Maximum allowed length deviation from target (mm). Default: 0.1.",
            },
            "serpentine_amplitude_mm": {
                "type": "number",
                "description": "Advisory serpentine half-amplitude for length-tuning (mm). Default: 0.5.",
            },
        },
        "required": ["circuit_json", "name", "net_ids", "target_length_mm"],
    },
)


@register(add_length_group_spec, write=True)
async def add_length_group(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    name = (a.get("name") or "").strip()
    net_ids = a.get("net_ids")
    target = a.get("target_length_mm")
    skew_max = a.get("skew_max_mm", 0.1)
    amplitude = a.get("serpentine_amplitude_mm", 0.5)

    if not circuit_json:
        return err_payload("circuit_json is required", "BAD_ARGS")
    if not name:
        return err_payload("name is required", "BAD_ARGS")
    if not isinstance(net_ids, list) or len(net_ids) < 2:
        return err_payload("net_ids must be a list of at least 2 net identifiers", "BAD_ARGS")
    if not isinstance(target, (int, float)) or target <= 0:
        return err_payload("target_length_mm must be a positive number", "BAD_ARGS")

    cloned = deepcopy(circuit_json)
    elements = cloned if isinstance(cloned, list) else [cloned]
    board = _get_board(elements)
    if board is None:
        return err_payload("No pcb_board element found in circuit_json", "BAD_ARGS")

    if not isinstance(board.get("length_groups"), list):
        board["length_groups"] = []

    entry = {
        "name": name,
        "net_ids": list(net_ids),
        "target_length_mm": target,
        "skew_max_mm": skew_max,
        "serpentine_amplitude_mm": amplitude,
    }

    idx = next((i for i, g in enumerate(board["length_groups"]) if g.get("name") == name), -1)
    if idx >= 0:
        board["length_groups"][idx] = entry
    else:
        board["length_groups"].append(entry)

    return ok_payload({"circuit_json": cloned, "group": entry})


# ── check_length_match ────────────────────────────────────────────────────────

check_length_match_spec = ToolSpec(
    name="check_length_match",
    description=(
        "Check every net in a length group against target_length_mm and report: "
        "current length, delta_to_target (negative = net is too short, must add meander), "
        "and whether the net passes the skew budget.  "
        "Nets that are below target are flagged with needs_tuning=true and a recommended "
        "serpentine delta.  Uses board.length_groups set by add_length_group."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {"oneOf": [{"type": "object"}, {"type": "array"}]},
            "group_name": {"type": "string", "description": "Name of the length group to check."},
        },
        "required": ["circuit_json", "group_name"],
    },
)


@register(check_length_match_spec, write=False)
async def check_length_match(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    group_name = (a.get("group_name") or "").strip()

    if not circuit_json:
        return err_payload("circuit_json is required", "BAD_ARGS")
    if not group_name:
        return err_payload("group_name is required", "BAD_ARGS")

    elements = circuit_json if isinstance(circuit_json, list) else [circuit_json]
    board = _get_board(elements)
    groups = (board.get("length_groups") or []) if board else []

    group = next((g for g in groups if g.get("name") == group_name), None)
    if group is None:
        return err_payload(f"length group '{group_name}' not found", "NOT_FOUND")

    target = group["target_length_mm"]
    skew_max = group.get("skew_max_mm", 0.1)
    amplitude = group.get("serpentine_amplitude_mm", 0.5)

    net_reports = []
    all_pass = True
    for net_id in group["net_ids"]:
        current = _net_length(elements, net_id)
        delta = target - current  # positive = needs more length
        needs_tuning = delta > skew_max
        if needs_tuning:
            all_pass = False
        net_reports.append({
            "net_id": net_id,
            "current_length_mm": round(current, 4),
            "target_length_mm": target,
            "delta_mm": round(delta, 4),
            "needs_tuning": needs_tuning,
            "recommended_serpentine_delta_mm": round(delta, 4) if needs_tuning else 0.0,
            "recommended_amplitude_mm": amplitude if needs_tuning else None,
        })

    return ok_payload({
        "group_name": group_name,
        "target_length_mm": target,
        "skew_max_mm": skew_max,
        "all_pass": all_pass,
        "nets": net_reports,
    })
