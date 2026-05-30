"""B-rep edge-length metrics for cutting-cost estimation.

Computes total edge length of a B-rep model and classifies edges by:

  1. **Topological kind** (uses the same radial-edge classification as
     ``brep_connect_inspector``, Wave 4OO):
       - boundary    — radial valence == 1
       - manifold    — radial valence == 2
       - nonmanifold — radial valence >= 3
       - total       — sum over all distinct edges

  2. **Curve type** (classify the underlying geometry):
       - linear    — degree-1 NurbsCurve or straight Euclidean chord
       - circular  — rational degree-2 NurbsCurve with uniform-ish weights
                     (NURBS circle construction; Lee 1987 / Piegl-Tiller §7.2)
       - freeform  — everything else (degree ≥ 2 non-circle, degree ≥ 3 B-splines)
       - total     — sum over all distinct edges

Edge-length computation (depth-bar compliant)
---------------------------------------------
* **Linear edges** — Euclidean distance ‖end − start‖ from ``vertex_coords``.
  Falls back to the ``length`` field on the edge dict if coords are absent.
* **Circular edges** — radius × subtended angle:
    radius     = from ``circle_radius`` hint field
    angle      = from ``arc_angle`` hint field, or computed from center+endpoints
* **Freeform NurbsCurves** — adaptive 5-point Gauss-Legendre via
  ``arc_length_gauss.arc_length_precise`` (Stoer-Bulirsch §3 + Piegl-Tiller §5.4).
  Honest-flag: if the adaptive integrator cannot guarantee < 1e-6 absolute error
  on a particular edge (max_depth hit at depth 20), ``EdgeMetricsReport.warnings``
  will contain a message for that edge.

Input contract
--------------
Each face dict may optionally extend the base brep_connect_inspector schema with
curve-type hints per edge::

    {
        "face_id": <hashable>,
        "edges": [
            {
                "edge_id": <hashable>,
                "start": <hashable>,
                "end":   <hashable>,
                "length": <float|None>,        # pre-computed length (fallback)
                # Geometry hints (optional — enable richer computation):
                "vertex_coords": {             # 3-D vertex positions
                    "<vertex_id>": [x, y, z],
                    ...
                },
                "curve": {                     # underlying NURBS curve
                    "degree": <int>,
                    "control_points": [[x,y,z], ...],
                    "knots": [float, ...],
                    "weights": [float, ...] | null,
                },
                "circle_center": [x, y, z],    # for circular arc edges
                "circle_radius": <float>,       # radius in model units
                "arc_angle": <float>,           # subtended angle in radians
            },
            ...
        ]
    }

If neither curve geometry nor vertex_coords is supplied, the module falls back to
the ``length`` field on the edge dict.  Edges with no length info contribute 0.0
and are noted in warnings.

Public API
----------
    total_edge_length(faces) -> float
    edge_length_by_kind(faces) -> EdgeKindMetrics
    edges_by_curve_type(faces) -> EdgeCurveTypeMetrics
    compute_edge_metrics(faces) -> EdgeMetricsReport

LLM tools ``brep_total_edge_length`` and ``brep_edge_length_by_kind`` are
registered when ``kerf_chat`` is available.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep_connect_inspector import inspect_connectivity

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EdgeKindMetrics:
    """Edge-length sums partitioned by radial valence (Weiler 1985 §3)."""
    boundary: float = 0.0       # edges with valence == 1
    manifold: float = 0.0       # edges with valence == 2
    nonmanifold: float = 0.0    # edges with valence >= 3
    total: float = 0.0          # sum over all distinct edges


@dataclass
class EdgeCurveTypeMetrics:
    """Edge-length sums partitioned by underlying curve geometry."""
    linear: float = 0.0         # degree-1 or straight chord
    circular: float = 0.0       # rational degree-2 circle arcs
    freeform: float = 0.0       # all other (parametric / polynomial)
    total: float = 0.0          # sum over all distinct edges


@dataclass
class EdgeMetricsReport:
    """Full edge-metrics report combining kind and curve-type breakdowns."""
    total_length: float
    by_kind: EdgeKindMetrics
    by_curve_type: EdgeCurveTypeMetrics
    edge_count: int
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _euclidean(a: List[float], b: List[float]) -> float:
    """Return ‖b − a‖ in 3-D (or 2-D)."""
    da = np.asarray(a, dtype=float)
    db = np.asarray(b, dtype=float)
    return float(np.linalg.norm(db - da))


def _is_circle_nurbs(degree: int, weights: Optional[List[float]]) -> bool:
    """Heuristic: rational degree-2 NURBS with non-unit weights ≈ circle arc.

    A standard NURBS circle (Piegl-Tiller §7.2 / Lee 1987) is degree 2,
    rational, and uses weights [1, cos(Δθ/2), 1, cos(Δθ/2), ...].  We require:
      - degree == 2
      - weights are not all 1 (i.e. truly rational)
      - all weights > 0  (no negative weights)
    """
    if degree != 2:
        return False
    if weights is None or len(weights) == 0:
        return False
    w = np.asarray(weights, dtype=float)
    if np.allclose(w, 1.0):
        return False       # non-rational degree-2 = parabola, not circle
    return bool(np.all(w > 0.0))


def _arc_angle_from_circle_and_chord(
    radius: float,
    start: List[float],
    end: List[float],
    center: List[float],
) -> float:
    """Compute the subtended angle of an arc from the geometry.

    Uses the dot-product between the two radius vectors to find the angle.
    Returns a value in [0, 2π].
    """
    c = np.asarray(center, dtype=float)
    s = np.asarray(start, dtype=float)
    e = np.asarray(end, dtype=float)
    vs = s - c
    ve = e - c
    ns = np.linalg.norm(vs)
    ne = np.linalg.norm(ve)
    if ns < 1e-14 or ne < 1e-14:
        return 0.0
    cos_a = float(np.dot(vs, ve) / (ns * ne))
    cos_a = max(-1.0, min(1.0, cos_a))
    return math.acos(cos_a)


# ---------------------------------------------------------------------------
# Edge geometry: deduplicate + compute length
# ---------------------------------------------------------------------------

def _build_edge_table(
    faces: Iterable[Dict],
) -> Tuple[Dict[Any, float], Dict[Any, str], List[str], Dict[Any, int]]:
    """Walk the face list once, return (lengths, curve_types, warnings, valences).

    Returns
    -------
    lengths    : edge_id → computed length (float)
    curve_types: edge_id → 'linear' | 'circular' | 'freeform'
    warnings   : list of warning strings
    valences   : edge_id → radial valence count
    """
    faces_list = list(faces)
    # Reuse inspect_connectivity only for its topology checks.
    inspect_connectivity(faces_list)  # validates input; result discarded

    # Build valence map and deduplicate edges.
    edge_valence: Dict[Any, int] = defaultdict(int)
    edge_raw: Dict[Any, Dict] = {}   # first occurrence of each edge dict

    for face in faces_list:
        for edge in face.get("edges", []):
            eid = edge["edge_id"]
            edge_valence[eid] += 1
            if eid not in edge_raw:
                edge_raw[eid] = edge

    warn_list: List[str] = []
    lengths: Dict[Any, float] = {}
    curve_types: Dict[Any, str] = {}

    for eid, edict in edge_raw.items():
        length, ctype, w = _compute_edge_length(eid, edict)
        lengths[eid] = length
        curve_types[eid] = ctype
        warn_list.extend(w)

    return lengths, curve_types, warn_list, dict(edge_valence)


def _compute_edge_length(
    eid: Any,
    edict: Dict,
) -> Tuple[float, str, List[str]]:
    """Return (length, curve_type, warnings) for one edge dict."""
    warns: List[str] = []
    ctype = "freeform"  # default
    length = 0.0

    # --- Try to get vertex positions -----------------------------------------
    vcoords: Optional[Dict] = edict.get("vertex_coords")
    start_id = edict.get("start")
    end_id   = edict.get("end")

    start_pt: Optional[List[float]] = None
    end_pt:   Optional[List[float]] = None
    if vcoords and start_id is not None and end_id is not None:
        if start_id in vcoords:
            start_pt = list(vcoords[start_id])
        if end_id in vcoords:
            end_pt = list(vcoords[end_id])

    # --- Try NURBS curve hint -------------------------------------------------
    curve_hint = edict.get("curve")
    if curve_hint is not None:
        deg = int(curve_hint.get("degree", 1))
        cp_raw  = curve_hint.get("control_points", [])
        kn_raw  = curve_hint.get("knots", [])
        wt_raw  = curve_hint.get("weights")

        if deg == 1 and len(cp_raw) >= 2:
            # --- Linear -------------------------------------------------------
            ctype = "linear"
            if start_pt is not None and end_pt is not None:
                length = _euclidean(start_pt, end_pt)
            elif len(cp_raw) >= 2:
                length = _euclidean(cp_raw[0], cp_raw[-1])
            else:
                length = float(edict.get("length") or 0.0)

        elif _is_circle_nurbs(deg, wt_raw):
            # --- Circular arc -------------------------------------------------
            ctype = "circular"
            # Prefer explicit circle_radius + arc_angle shortcut
            if "circle_radius" in edict and "arc_angle" in edict:
                length = float(edict["circle_radius"]) * float(edict["arc_angle"])
            elif "circle_radius" in edict and "circle_center" in edict and start_pt and end_pt:
                r = float(edict["circle_radius"])
                angle = _arc_angle_from_circle_and_chord(
                    r, start_pt, end_pt, edict["circle_center"]
                )
                length = r * angle
            else:
                # Fall back to Gauss-Legendre on the NURBS circle curve
                length, warns_gl = _gauss_legendre_nurbs(eid, deg, cp_raw, kn_raw, wt_raw)
                warns.extend(warns_gl)

        else:
            # --- Freeform NurbsCurve ------------------------------------------
            ctype = "freeform"
            length, warns_gl = _gauss_legendre_nurbs(eid, deg, cp_raw, kn_raw, wt_raw)
            warns.extend(warns_gl)

    else:
        # --- No curve hint: check circle hints first, then vertex coords -----
        if "circle_radius" in edict and "arc_angle" in edict:
            # Explicit arc-length shortcut: r × θ (highest priority, no coords needed)
            ctype = "circular"
            length = float(edict["circle_radius"]) * float(edict["arc_angle"])
        elif "circle_radius" in edict and "circle_center" in edict and start_pt is not None and end_pt is not None:
            ctype = "circular"
            r = float(edict["circle_radius"])
            angle = _arc_angle_from_circle_and_chord(
                r, start_pt, end_pt, edict["circle_center"]
            )
            length = r * angle
        elif start_pt is not None and end_pt is not None:
            # Straight chord — assume linear
            ctype = "linear"
            length = _euclidean(start_pt, end_pt)
        else:
            # Last resort: use the "length" field on the edge dict
            raw_len = edict.get("length")
            if raw_len is not None:
                length = float(raw_len)
                ctype = "linear"  # can't determine curve type; assume linear
            else:
                warns.append(
                    f"edge {eid!r}: no geometry info and no 'length' field; "
                    "contributing 0.0 to total."
                )
                length = 0.0
                ctype = "linear"

    return length, ctype, warns


def _gauss_legendre_nurbs(
    eid: Any,
    degree: int,
    cp_raw: List,
    kn_raw: List,
    wt_raw: Optional[List],
) -> Tuple[float, List[str]]:
    """Integrate arc length of a NurbsCurve via adaptive GL.  Return (length, warns)."""
    from kerf_cad_core.geom.nurbs import NurbsCurve
    from kerf_cad_core.geom.arc_length_gauss import arc_length_precise

    warns: List[str] = []
    try:
        ctrl = np.asarray(cp_raw, dtype=float)
        knots = np.asarray(kn_raw, dtype=float)
        weights = np.asarray(wt_raw, dtype=float) if wt_raw else None
        curve = NurbsCurve(degree=degree, control_points=ctrl, knots=knots, weights=weights)
    except Exception as exc:
        warns.append(f"edge {eid!r}: failed to build NurbsCurve ({exc}); contributing 0.0.")
        return 0.0, warns

    # Compute with tight tolerances; use max_depth=20 (default).
    # Also compute a coarser estimate (max_depth=5) to detect convergence
    # problems and raise an honest flag when |error| > 1e-6.
    try:
        length_precise = arc_length_precise(
            curve, rel_tol=1e-9, abs_tol=1e-12, max_depth=20
        )
        length_coarse = arc_length_precise(
            curve, rel_tol=1e-4, abs_tol=1e-6, max_depth=5
        )
    except Exception as exc:
        warns.append(f"edge {eid!r}: arc_length_precise failed ({exc}); contributing 0.0.")
        return 0.0, warns

    err_estimate = abs(length_precise - length_coarse)
    if err_estimate > 1e-6:
        warns.append(
            f"edge {eid!r}: Gauss-Legendre convergence flag — |precise − coarse| = "
            f"{err_estimate:.3e} > 1e-6; result may not satisfy 1e-6 abs tolerance."
        )

    return length_precise, warns


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def total_edge_length(faces: Iterable[Dict]) -> float:
    """Compute the total edge length of a B-rep model.

    Parameters
    ----------
    faces:
        Iterable of face dicts as described in the module docstring.
        Uses the same schema as ``brep_connect_inspector``.

    Returns
    -------
    float
        Sum of lengths over all *distinct* edges (mm or model units).
        Each edge is counted once regardless of how many faces reference it.

    Notes
    -----
    * Linear edges: Euclidean ‖end − start‖ from ``vertex_coords``.
    * Circular edges: radius × subtended angle.
    * Freeform NurbsCurves: adaptive 5-point Gauss-Legendre quadrature.
    * Falls back to the ``length`` field if no geometry is available.
    * Returns 0.0 for empty input.
    """
    faces_list = list(faces)
    if not faces_list:
        return 0.0
    lengths, _, _, _ = _build_edge_table(faces_list)
    return sum(lengths.values())


def edge_length_by_kind(faces: Iterable[Dict]) -> EdgeKindMetrics:
    """Return edge-length sums partitioned by radial valence.

    Uses the same Weiler 1985 §3 radial-edge classification as
    ``brep_connect_inspector.inspect_connectivity``:

      - boundary    valence == 1 (open/free edges)
      - manifold    valence == 2 (interior shared edges)
      - nonmanifold valence >= 3 (non-manifold topology)
      - total       sum over all distinct edges

    Parameters
    ----------
    faces:
        Iterable of face dicts.

    Returns
    -------
    EdgeKindMetrics
    """
    faces_list = list(faces)
    if not faces_list:
        return EdgeKindMetrics()
    lengths, _, _, valences = _build_edge_table(faces_list)

    result = EdgeKindMetrics()
    for eid, l in lengths.items():
        v = valences.get(eid, 0)
        if v == 1:
            result.boundary += l
        elif v == 2:
            result.manifold += l
        elif v >= 3:
            result.nonmanifold += l
        result.total += l
    return result


def edges_by_curve_type(faces: Iterable[Dict]) -> EdgeCurveTypeMetrics:
    """Return edge-length sums partitioned by underlying curve geometry.

    Classification:
      - linear    — degree-1 NurbsCurve or straight chord (vertex-coords only)
      - circular  — rational degree-2 NURBS (Lee 1987 / Piegl-Tiller §7.2),
                    or edge with ``circle_radius`` + ``arc_angle``/``circle_center``
      - freeform  — all other NURBS curves (polynomial or rational, degree ≥ 2)
      - total     — sum over all distinct edges

    Arc lengths:
      - linear  → Euclidean distance
      - circular → radius × angle (from hint fields or GL on NURBS circle)
      - freeform → adaptive 5-point Gauss-Legendre

    Parameters
    ----------
    faces:
        Iterable of face dicts.

    Returns
    -------
    EdgeCurveTypeMetrics
    """
    faces_list = list(faces)
    if not faces_list:
        return EdgeCurveTypeMetrics()
    lengths, curve_types, _, _ = _build_edge_table(faces_list)

    result = EdgeCurveTypeMetrics()
    for eid, l in lengths.items():
        ct = curve_types.get(eid, "freeform")
        if ct == "linear":
            result.linear += l
        elif ct == "circular":
            result.circular += l
        else:
            result.freeform += l
        result.total += l
    return result


def compute_edge_metrics(faces: Iterable[Dict]) -> EdgeMetricsReport:
    """Full edge-metrics report: kind breakdown + curve-type breakdown.

    Parameters
    ----------
    faces:
        Iterable of face dicts.

    Returns
    -------
    EdgeMetricsReport
        Contains total_length, by_kind, by_curve_type, edge_count, warnings.
    """
    faces_list = list(faces)
    if not faces_list:
        return EdgeMetricsReport(
            total_length=0.0,
            by_kind=EdgeKindMetrics(),
            by_curve_type=EdgeCurveTypeMetrics(),
            edge_count=0,
        )

    lengths, curve_types, warns, valences = _build_edge_table(faces_list)

    by_kind = EdgeKindMetrics()
    by_ctype = EdgeCurveTypeMetrics()

    for eid, l in lengths.items():
        v = valences.get(eid, 0)
        if v == 1:
            by_kind.boundary += l
        elif v == 2:
            by_kind.manifold += l
        elif v >= 3:
            by_kind.nonmanifold += l
        by_kind.total += l

        ct = curve_types.get(eid, "freeform")
        if ct == "linear":
            by_ctype.linear += l
        elif ct == "circular":
            by_ctype.circular += l
        else:
            by_ctype.freeform += l
        by_ctype.total += l

    return EdgeMetricsReport(
        total_length=by_kind.total,
        by_kind=by_kind,
        by_curve_type=by_ctype,
        edge_count=len(lengths),
        warnings=warns,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

# Shared face-list JSON schema (mirrors brep_connect_inspector_tools)
_FACES_SCHEMA = {
    "type": "array",
    "description": (
        "List of B-rep faces.  Each face has 'face_id' and an 'edges' list. "
        "Each edge has 'edge_id', 'start', 'end', optional 'length'. "
        "For geometric precision, supply per-edge 'vertex_coords' (dict of "
        "vertex_id → [x,y,z]) and/or a 'curve' dict with 'degree', "
        "'control_points', 'knots', 'weights'.  Circular arcs may also "
        "use 'circle_radius', 'arc_angle', 'circle_center'."
    ),
    "items": {
        "type": "object",
        "properties": {
            "face_id": {"type": ["string", "integer"]},
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "edge_id":       {"type": ["string", "integer"]},
                        "start":         {"type": ["string", "integer"]},
                        "end":           {"type": ["string", "integer"]},
                        "length":        {"type": "number"},
                        "vertex_coords": {"type": "object"},
                        "circle_radius": {"type": "number"},
                        "arc_angle":     {"type": "number"},
                        "circle_center": {"type": "array", "items": {"type": "number"}},
                        "curve": {
                            "type": "object",
                            "properties": {
                                "degree":         {"type": "integer"},
                                "control_points": {"type": "array"},
                                "knots":          {"type": "array"},
                                "weights":        {"type": ["array", "null"]},
                            },
                            "required": ["degree", "control_points", "knots"],
                        },
                    },
                    "required": ["edge_id", "start", "end"],
                },
            },
        },
        "required": ["face_id", "edges"],
    },
}


if _REGISTRY_AVAILABLE:

    # ---- brep_total_edge_length -----------------------------------------------

    _total_spec = ToolSpec(
        name="brep_total_edge_length",
        description=(
            "Compute the total edge length of a B-rep model (mm or model units). "
            "Each distinct edge is counted exactly once.\n\n"
            "Arc-length methods:\n"
            "  • linear edges — Euclidean ‖end−start‖ from vertex_coords\n"
            "  • circular arc edges — radius × subtended angle\n"
            "  • freeform NURBS — adaptive 5-point Gauss-Legendre (Stoer-Bulirsch §3 + "
            "Piegl-Tiller §5.4)\n\n"
            "Reference oracles: 100×50 rectangle → 300; unit cube → 12; "
            "sphere with 12 great-circle arcs r=50 → 3769.91\n\n"
            "Returns: {ok, total_length, edge_count, warnings}"
        ),
        input_schema={
            "type": "object",
            "properties": {"faces": _FACES_SCHEMA},
            "required": ["faces"],
        },
    )

    @register(_total_spec)
    async def run_brep_total_edge_length(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        faces = a.get("faces")
        if faces is None:
            return err_payload("'faces' is required", "BAD_ARGS")
        try:
            report = compute_edge_metrics(faces)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")
        return ok_payload({
            "total_length": report.total_length,
            "edge_count": report.edge_count,
            "warnings": report.warnings,
        })

    # ---- brep_edge_length_by_kind -------------------------------------------

    _by_kind_spec = ToolSpec(
        name="brep_edge_length_by_kind",
        description=(
            "Compute total edge length of a B-rep model and break it down by "
            "radial-edge valence (Weiler 1985 §3) — the same classification as "
            "brep_inspect_connectivity:\n"
            "  boundary    — valence 1 (open / free edges)\n"
            "  manifold    — valence 2 (interior shared edges)\n"
            "  nonmanifold — valence ≥ 3 (non-manifold topology)\n"
            "  total       — sum over all distinct edges\n\n"
            "Also returns a curve-type breakdown (linear / circular / freeform / total) "
            "and an edge count.\n\n"
            "Returns: {ok, total_length, by_kind, by_curve_type, edge_count, warnings}"
        ),
        input_schema={
            "type": "object",
            "properties": {"faces": _FACES_SCHEMA},
            "required": ["faces"],
        },
    )

    @register(_by_kind_spec)
    async def run_brep_edge_length_by_kind(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        faces = a.get("faces")
        if faces is None:
            return err_payload("'faces' is required", "BAD_ARGS")
        try:
            report = compute_edge_metrics(faces)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")
        return ok_payload({
            "total_length":  report.total_length,
            "by_kind": {
                "boundary":    report.by_kind.boundary,
                "manifold":    report.by_kind.manifold,
                "nonmanifold": report.by_kind.nonmanifold,
                "total":       report.by_kind.total,
            },
            "by_curve_type": {
                "linear":   report.by_curve_type.linear,
                "circular": report.by_curve_type.circular,
                "freeform": report.by_curve_type.freeform,
                "total":    report.by_curve_type.total,
            },
            "edge_count": report.edge_count,
            "warnings":   report.warnings,
        })
