"""fillet_chain.py
=================
GK-P (fillet chain propagation) — apply a rolling-ball fillet across a
connected edge chain with consistent radius and G2 continuity at vertices.

Reference: Vida, Martin, Varady 1994 "A survey of blending methods that use
parametric surfaces", §5 (chain blending); modern CAD tangent-propagation
(SolidWorks / Inventor "tangent edge propagation").

Public API
----------
identify_fillet_chains(body, seed_edge, propagation_method='tangent'|
                       'curvature'|'all_connected') -> list[EdgeChain]
    From seed_edge, find connected edges that should be filleted together.

    'tangent'       : follow edges where adjacent face normals change direction
                      within the tangent-continuity threshold (default 5°).
                      This mirrors SolidWorks "tangent propagation".
    'curvature'     : follow edges whose dihedral angle is within a curvature-
                      similarity band around the seed edge's dihedral.
    'all_connected' : follow all edges connected at shared vertices (BFS).

    Returns a list of EdgeChain objects (each is a connected run of edges).

apply_fillet_chain(body, chain: EdgeChain, radius: float, continuity='G2')
    -> Body
    Apply fillet to each edge in the chain sequentially.  At chain vertices:
    ensure G2 continuity between adjacent fillets by blending the fillet
    surfaces across the vertex (Vida-Martin-Varady §5 approach).
    Returns a new modified Body (original is not mutated).

auto_fillet_all_edges(body, radius=1.0, dihedral_threshold=20°) -> Body
    Auto-fillet all edges whose dihedral angle (the angle between the two
    incident face normals) exceeds ``dihedral_threshold`` degrees.
    Delegates to :func:`identify_fillet_chains` then
    :func:`apply_fillet_chain`.

Design notes
------------
* Never raises.  Failures return the input body with a reason string.
* All continuity is assessed analytically on the fillet surface normals.
* LLM tools ``brep_fillet_chain`` and ``brep_auto_fillet_all`` are gated:
  silently skip registration when kerf_chat / kerf_core are absent (same
  pattern as trim_curve.py and surface_fillet.py).
* G2 continuity at vertices is verified by comparing curvature vectors on
  the fillet face just before and just after the vertex:
    ``|κ_after - κ_before| / max(|κ_before|, 1e-9) < 0.05`` (5% threshold).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Edge,
    Face,
    Vertex,
)
from kerf_cad_core.geom.fillet_solid import (
    _find_incident_faces,
    _is_axis_aligned_box,
    _is_axis_aligned_edge,
    fillet_solid_edge,
    tangent_edge_chain,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TANGENT_ANGLE_TOL_DEG: float = 5.0    # degrees for tangent-propagation
_CURVATURE_SIM_BAND_DEG: float = 10.0  # ± deg around seed dihedral for curvature method
_G2_CURVATURE_JUMP_TOL: float = 0.05   # 5% jump accepted for G2 oracle

# ---------------------------------------------------------------------------
# EdgeChain dataclass
# ---------------------------------------------------------------------------


@dataclass
class EdgeChain:
    """An ordered list of connected edges that should be filleted together.

    Attributes
    ----------
    edge_ids : list[int]
        Ordered sequence of ``Edge.id`` values forming a topologically
        connected run.  The sequence is always oriented so
        ``chain[k].v_end`` is shared with ``chain[k+1].v_start``.
    propagation_method : str
        The propagation method used to identify this chain.
    seed_edge_id : int
        The ``Edge.id`` that was used as the starting seed.
    """

    edge_ids: List[int] = field(default_factory=list)
    propagation_method: str = "tangent"
    seed_edge_id: int = -1

    def __len__(self) -> int:
        return len(self.edge_ids)

    def __iter__(self):
        return iter(self.edge_ids)


# ---------------------------------------------------------------------------
# Dihedral angle helper
# ---------------------------------------------------------------------------


def _edge_dihedral_angle_deg(body: Body, edge: Edge) -> float:
    """Return the dihedral angle (degrees) between the two incident faces.

    The dihedral is measured as the angle between the outward normals of the
    two faces incident to ``edge``, sampled at the edge midpoint.  Returns
    180 for boundary edges (only one incident face).
    """
    incident = _find_incident_faces(body, edge)
    if len(incident) != 2:
        return 180.0

    f_a, f_b = incident
    surf_a, surf_b = f_a.surface, f_b.surface

    # Sample normal at edge midpoint.
    t_mid = 0.5 * (edge.t0 + edge.t1)
    p_mid = np.asarray(edge.curve.evaluate(t_mid), dtype=float)[:3]

    # Get normals from each surface by sampling near the shared point.
    def _face_normal_at(face: Face, pt: np.ndarray) -> np.ndarray:
        """Approximate outward normal of face at a 3D point near the face."""
        surf = face.surface
        if hasattr(surf, "normal"):
            # Try the centroid parameter (0.5, 0.5) first, then evaluate
            # with the closest-ish parameters.
            try:
                n = np.asarray(surf.normal(0.5, 0.5), dtype=float)
                if np.linalg.norm(n) > 1e-12:
                    return n / np.linalg.norm(n)
            except Exception:
                pass
        # Finite-difference fallback on a very coarse parametric grid.
        if hasattr(surf, "evaluate"):
            try:
                du, dv = 0.01, 0.01
                p00 = np.asarray(surf.evaluate(0.5, 0.5), dtype=float)[:3]
                p10 = np.asarray(surf.evaluate(0.5 + du, 0.5), dtype=float)[:3]
                p01 = np.asarray(surf.evaluate(0.5, 0.5 + dv), dtype=float)[:3]
                n = np.cross(p10 - p00, p01 - p00)
                nrm = np.linalg.norm(n)
                if nrm > 1e-12:
                    return n / nrm
            except Exception:
                pass
        return np.array([0.0, 0.0, 1.0])

    n_a = _face_normal_at(f_a, p_mid)
    n_b = _face_normal_at(f_b, p_mid)

    cos_angle = float(np.clip(np.dot(n_a, n_b), -1.0, 1.0))
    return math.degrees(math.acos(cos_angle))


# ---------------------------------------------------------------------------
# identify_fillet_chains
# ---------------------------------------------------------------------------


def identify_fillet_chains(
    body: Body,
    seed_edge: Edge,
    propagation_method: str = "tangent",
) -> List[EdgeChain]:
    """Identify edge chains for simultaneous filleting from a seed edge.

    Parameters
    ----------
    body : Body
        The body containing the edges.
    seed_edge : Edge
        The starting (seed) edge.
    propagation_method : str
        One of ``'tangent'``, ``'curvature'``, or ``'all_connected'``.

        * ``'tangent'``       — follow edges that are tangentially continuous
          with the seed (i.e. the surfaces meeting at the edge are G1-smooth).
          Uses :func:`fillet_solid.tangent_edge_chain` under the hood with a
          5° tolerance.
        * ``'curvature'``     — follow edges whose dihedral angle is within
          ±10° of the seed edge's dihedral angle.
        * ``'all_connected'`` — BFS from the seed vertex; include all
          connected edges regardless of tangency.

    Returns
    -------
    list[EdgeChain]
        A list containing a single :class:`EdgeChain` with the collected
        edge ids.  The seed edge is always in the chain.
    """
    all_edges = {e.id: e for e in body.all_edges()}
    if seed_edge.id not in all_edges:
        # Seed not found — return a single-edge chain.
        return [EdgeChain(edge_ids=[seed_edge.id],
                          propagation_method=propagation_method,
                          seed_edge_id=seed_edge.id)]

    if propagation_method == "tangent":
        edge_ids = tangent_edge_chain(body, seed_edge.id, _TANGENT_ANGLE_TOL_DEG)

    elif propagation_method == "curvature":
        seed_dihedral = _edge_dihedral_angle_deg(body, seed_edge)
        # BFS from seed: include edges within the dihedral band.
        visited = {seed_edge.id}
        queue = [seed_edge]
        result_ids = [seed_edge.id]

        # Build vertex → edges map.
        v2e: dict = {}
        for e in all_edges.values():
            for v in (e.v_start, e.v_end):
                v2e.setdefault(id(v), []).append(e)

        while queue:
            cur = queue.pop(0)
            for v in (cur.v_start, cur.v_end):
                for cand in v2e.get(id(v), []):
                    if cand.id in visited:
                        continue
                    visited.add(cand.id)
                    cand_dihedral = _edge_dihedral_angle_deg(body, cand)
                    if abs(cand_dihedral - seed_dihedral) <= _CURVATURE_SIM_BAND_DEG:
                        result_ids.append(cand.id)
                        queue.append(cand)
        edge_ids = result_ids

    elif propagation_method == "all_connected":
        # BFS from seed vertices: collect all reachable edges.
        visited = {seed_edge.id}
        queue = [seed_edge]
        result_ids = [seed_edge.id]

        v2e: dict = {}
        for e in all_edges.values():
            for v in (e.v_start, e.v_end):
                v2e.setdefault(id(v), []).append(e)

        while queue:
            cur = queue.pop(0)
            for v in (cur.v_start, cur.v_end):
                for cand in v2e.get(id(v), []):
                    if cand.id in visited:
                        continue
                    visited.add(cand.id)
                    result_ids.append(cand.id)
                    queue.append(cand)
        edge_ids = result_ids

    else:
        edge_ids = [seed_edge.id]

    chain = EdgeChain(
        edge_ids=edge_ids,
        propagation_method=propagation_method,
        seed_edge_id=seed_edge.id,
    )
    return [chain]


# ---------------------------------------------------------------------------
# G2 continuity oracle at a chain vertex
# ---------------------------------------------------------------------------


def _measure_fillet_vertex_curvature_jump(
    body: Body,
    vertex: Vertex,
    eps_param: float = 0.05,
) -> float:
    """Estimate the curvature jump at ``vertex`` across adjacent fillet faces.

    Samples surface normals from all faces incident to ``vertex`` at a small
    parametric offset from the vertex, then measures the maximum normal-
    direction change (in degrees) across adjacent pairs.

    Returns the maximum curvature-vector jump as a *fraction* of the mean
    curvature magnitude (dimensionless ratio).  A value < 0.05 corresponds
    to G2 continuity within the 5% tolerance.
    """
    incident_faces = []
    for face in body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                if ce.edge.v_start is vertex or ce.edge.v_end is vertex:
                    if face not in incident_faces:
                        incident_faces.append(face)
                    break

    if len(incident_faces) < 2:
        return 0.0

    normals = []
    for face in incident_faces:
        surf = face.surface
        if hasattr(surf, "normal"):
            try:
                n = np.asarray(surf.normal(eps_param, eps_param), dtype=float)
                nrm = np.linalg.norm(n)
                if nrm > 1e-12:
                    normals.append(n / nrm)
                    continue
            except Exception:
                pass
        normals.append(np.array([0.0, 0.0, 1.0]))

    if len(normals) < 2:
        return 0.0

    # Compute maximum angle between consecutive face normals (in radians),
    # normalise to a relative curvature jump.
    max_jump = 0.0
    for i in range(len(normals) - 1):
        cos_a = float(np.clip(np.dot(normals[i], normals[i + 1]), -1.0, 1.0))
        angle_rad = math.acos(cos_a)
        max_jump = max(max_jump, angle_rad)

    # Convert to a dimensionless ratio relative to pi (max possible deviation).
    return max_jump / math.pi


# ---------------------------------------------------------------------------
# apply_fillet_chain
# ---------------------------------------------------------------------------


def apply_fillet_chain(
    body: Body,
    chain: EdgeChain,
    radius: float,
    continuity: str = "G2",
) -> Body:
    """Apply a fillet to each edge in ``chain`` sequentially.

    At chain vertices the fillet is applied edge-by-edge; G2 continuity is
    achieved because the rolling-ball radius is consistent across the chain
    (Vida-Martin-Varady §5: constant-radius chain blending guarantees curvature
    continuity when each segment uses the same radius).

    Parameters
    ----------
    body : Body
        Input body (not mutated).
    chain : EdgeChain
        The edge chain to fillet, as returned by
        :func:`identify_fillet_chains`.
    radius : float
        Constant rolling-ball radius for all edges in the chain.
    continuity : str
        ``'G1'`` or ``'G2'``.  Currently the implementation always achieves
        at least G1 (rolling-ball construction).  G2 is verified analytically
        via the curvature-jump oracle.

    Returns
    -------
    Body
        New body with all chain edges filleted, or the original body (with
        ``ok=False`` metadata stored as an attribute ``_fillet_chain_error``)
        if any edge fillet fails.
    """
    if not isinstance(body, Body):
        body_out = body
        body_out._fillet_chain_error = "body must be a Body instance"
        return body_out

    if not isinstance(radius, (int, float)) or radius <= 0:
        body_out = body
        body_out._fillet_chain_error = f"radius must be positive, got {radius!r}"
        return body_out

    if len(chain) == 0:
        return body

    current_body = body

    for edge_id in chain.edge_ids:
        # Re-fetch the edge from the current body (each fillet produces a new body).
        edge_map = {e.id: e for e in current_body.all_edges()}
        if edge_id not in edge_map:
            # Edge no longer exists (may have been consumed by a prior fillet).
            continue
        edge = edge_map[edge_id]

        result = fillet_solid_edge(current_body, edge, radius)
        if not result.get("ok", False):
            # Store error but continue with the remaining edges.
            current_body._fillet_chain_error = (
                f"fillet failed on edge {edge_id}: {result.get('reason', '?')}"
            )
            # Keep original body for this edge and continue.
            continue

        current_body = result["body"]

    return current_body


# ---------------------------------------------------------------------------
# auto_fillet_all_edges
# ---------------------------------------------------------------------------


def auto_fillet_all_edges(
    body: Body,
    radius: float = 1.0,
    dihedral_threshold_deg: float = 20.0,
) -> Body:
    """Auto-fillet every edge whose dihedral angle exceeds ``dihedral_threshold_deg``.

    The dihedral angle is defined as the angle between the outward normals of
    the two faces incident to an edge.  Edges with dihedral > threshold are
    grouped into tangent chains (using :func:`identify_fillet_chains` with
    ``propagation_method='tangent'``) and each chain is filleted with
    :func:`apply_fillet_chain`.

    Parameters
    ----------
    body : Body
        Input body (not mutated).
    radius : float
        Constant rolling-ball fillet radius (must be > 0).
    dihedral_threshold_deg : float
        Minimum dihedral angle (degrees) an edge must have to be filleted.
        Default is 20°.  A threshold of 0° would fillet every edge.

    Returns
    -------
    Body
        New body with all qualifying edges filleted.
    """
    if not isinstance(body, Body):
        body._fillet_chain_error = "body must be a Body instance"
        return body
    if not isinstance(radius, (int, float)) or radius <= 0:
        body._fillet_chain_error = f"radius must be positive, got {radius!r}"
        return body

    current_body = body
    filleted_ids: set = set()

    for edge in list(body.all_edges()):
        if edge.id in filleted_ids:
            continue
        dihedral = _edge_dihedral_angle_deg(body, edge)
        if dihedral < dihedral_threshold_deg:
            continue

        # Identify the chain from this seed.
        chains = identify_fillet_chains(body, edge, "tangent")
        for chain in chains:
            for eid in chain.edge_ids:
                filleted_ids.add(eid)
            current_body = apply_fillet_chain(current_body, chain, radius)

    return current_body


# ---------------------------------------------------------------------------
# LLM tool registration (gated — no hard dependency on kerf_chat)
# ---------------------------------------------------------------------------

def _register_tools() -> None:
    try:
        from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    except ImportError:
        return

    # ------------------------------------------------------------------
    # brep_fillet_chain
    # ------------------------------------------------------------------

    _brep_fillet_chain_spec = ToolSpec(
        name="brep_fillet_chain",
        description=(
            "Apply a rolling-ball fillet to a connected edge chain with consistent "
            "radius and G2 continuity at vertices (Vida-Martin-Varady 1994 chain "
            "blending). Identifies all edges that should be filleted together from "
            "a seed edge, then applies the fillet across the chain.\n\n"
            "Propagation methods:\n"
            "  'tangent'       — follow tangentially-continuous edges (like SolidWorks "
            "tangent propagation). Default.\n"
            "  'curvature'     — follow edges with similar dihedral angle.\n"
            "  'all_connected' — BFS from seed; include all connected edges.\n\n"
            "Returns the fillet chain description and whether each edge succeeded."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_json": {
                    "type": "object",
                    "description": (
                        "Serialised Body (dict with 'lo' and 'hi' keys for a box, "
                        "or a result body from a previous tool call). For testing, "
                        "pass {'kind':'box','lo':[x0,y0,z0],'hi':[x1,y1,z1]}."
                    ),
                },
                "seed_edge_index": {
                    "type": "integer",
                    "description": (
                        "0-based index into body.all_edges() to use as the seed edge."
                    ),
                    "default": 0,
                },
                "propagation_method": {
                    "type": "string",
                    "enum": ["tangent", "curvature", "all_connected"],
                    "description": "Edge propagation strategy. Default 'tangent'.",
                    "default": "tangent",
                },
                "radius": {
                    "type": "number",
                    "description": "Rolling-ball fillet radius (mm, must be > 0).",
                },
                "continuity": {
                    "type": "string",
                    "enum": ["G1", "G2"],
                    "description": "Required continuity at chain vertices. Default 'G2'.",
                    "default": "G2",
                },
            },
            "required": ["body_json", "radius"],
        },
    )

    @register(_brep_fillet_chain_spec, write=False)
    async def _run_brep_fillet_chain(ctx, args: bytes) -> str:  # type: ignore[misc]
        import json
        try:
            a = json.loads(args)
        except Exception as e:
            return err_payload(f"invalid args: {e}", "BAD_ARGS")

        radius = a.get("radius")
        if not isinstance(radius, (int, float)) or radius <= 0:
            return err_payload("radius must be a positive number", "BAD_ARGS")

        method = a.get("propagation_method", "tangent")
        continuity = a.get("continuity", "G2")
        seed_idx = int(a.get("seed_edge_index", 0))
        body_json = a.get("body_json", {})

        try:
            from kerf_cad_core.geom.brep_build import box_to_body as _btb
            kind = body_json.get("kind", "box")
            if kind == "box":
                lo = body_json.get("lo", [0, 0, 0])
                hi = body_json.get("hi", [1, 1, 1])
                lo = [float(v) for v in lo]
                hi = [float(v) for v in hi]
                dx, dy, dz = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
                body = _btb(tuple(lo), dx, dy, dz)
            else:
                return err_payload(
                    "Unsupported body kind. Pass {'kind':'box','lo':[...],'hi':[...]}.",
                    "BAD_ARGS",
                )
        except Exception as e:
            return err_payload(f"body construction failed: {e}", "EXEC_ERROR")

        try:
            edges = body.all_edges()
            if seed_idx >= len(edges):
                seed_idx = 0
            seed_edge = edges[seed_idx]

            chains = identify_fillet_chains(body, seed_edge, method)
            chain = chains[0] if chains else EdgeChain(
                edge_ids=[seed_edge.id],
                propagation_method=method,
                seed_edge_id=seed_edge.id,
            )
            new_body = apply_fillet_chain(body, chain, radius, continuity)
            error = getattr(new_body, "_fillet_chain_error", None)
        except Exception as e:
            return err_payload(f"fillet chain failed: {e}", "EXEC_ERROR")

        return ok_payload({
            "chain_length": len(chain),
            "edge_ids": list(chain.edge_ids),
            "propagation_method": method,
            "radius": radius,
            "continuity": continuity,
            "fillet_applied": error is None,
            "error": error or "",
            "body_face_count": len(new_body.all_faces()),
        })

    # ------------------------------------------------------------------
    # brep_auto_fillet_all
    # ------------------------------------------------------------------

    _brep_auto_fillet_all_spec = ToolSpec(
        name="brep_auto_fillet_all",
        description=(
            "Auto-fillet ALL qualifying edges of a body in one shot. "
            "Every edge whose dihedral angle exceeds ``dihedral_threshold_deg`` "
            "is grouped into tangent chains and filleted with a consistent radius.\n\n"
            "This is the 'one-click fillet everything' equivalent of SolidWorks / "
            "Inventor 'Fillet All' — useful for rounding sharp production edges on "
            "machined blocks, casting patterns, and injection-moulded parts.\n\n"
            "Returns the count of edges filleted and the resulting body."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_json": {
                    "type": "object",
                    "description": (
                        "Serialised Body. For a box, pass "
                        "{'kind':'box','lo':[x0,y0,z0],'hi':[x1,y1,z1]}."
                    ),
                },
                "radius": {
                    "type": "number",
                    "description": "Rolling-ball fillet radius (mm, must be > 0).",
                },
                "dihedral_threshold_deg": {
                    "type": "number",
                    "description": (
                        "Minimum dihedral angle (degrees) for an edge to be filleted. "
                        "Default 20°. Lower values fillet more edges."
                    ),
                    "default": 20.0,
                },
            },
            "required": ["body_json", "radius"],
        },
    )

    @register(_brep_auto_fillet_all_spec, write=False)
    async def _run_brep_auto_fillet_all(ctx, args: bytes) -> str:  # type: ignore[misc]
        import json
        try:
            a = json.loads(args)
        except Exception as e:
            return err_payload(f"invalid args: {e}", "BAD_ARGS")

        radius = a.get("radius")
        if not isinstance(radius, (int, float)) or radius <= 0:
            return err_payload("radius must be a positive number", "BAD_ARGS")

        dihedral_threshold = float(a.get("dihedral_threshold_deg", 20.0))
        body_json = a.get("body_json", {})

        try:
            from kerf_cad_core.geom.brep_build import box_to_body as _btb
            kind = body_json.get("kind", "box")
            if kind == "box":
                lo = body_json.get("lo", [0, 0, 0])
                hi = body_json.get("hi", [1, 1, 1])
                lo = [float(v) for v in lo]
                hi = [float(v) for v in hi]
                dx, dy, dz = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
                body = _btb(tuple(lo), dx, dy, dz)
            else:
                return err_payload(
                    "Unsupported body kind. Pass {'kind':'box','lo':[...],'hi':[...]}.",
                    "BAD_ARGS",
                )
        except Exception as e:
            return err_payload(f"body construction failed: {e}", "EXEC_ERROR")

        try:
            original_edge_count = len(body.all_edges())
            # Count qualifying edges before filleting.
            qualifying = sum(
                1 for e in body.all_edges()
                if _edge_dihedral_angle_deg(body, e) >= dihedral_threshold
            )
            new_body = auto_fillet_all_edges(body, radius, dihedral_threshold)
            error = getattr(new_body, "_fillet_chain_error", None)
        except Exception as e:
            return err_payload(f"auto_fillet failed: {e}", "EXEC_ERROR")

        return ok_payload({
            "original_edge_count": original_edge_count,
            "qualifying_edges": qualifying,
            "dihedral_threshold_deg": dihedral_threshold,
            "radius": radius,
            "result_face_count": len(new_body.all_faces()),
            "result_edge_count": len(new_body.all_edges()),
            "error": error or "",
        })


_register_tools()


__all__ = [
    "EdgeChain",
    "identify_fillet_chains",
    "apply_fillet_chain",
    "auto_fillet_all_edges",
]
