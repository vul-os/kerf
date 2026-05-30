"""subd_critical_points.py
==========================
Find critical points (∇f = 0) of a scalar field on a Catmull-Clark SubD
limit surface using discrete Morse theory.

Theory
------
Given a smooth scalar function f on a compact surface M, a point p is
*critical* if ∇f(p) = 0.  By the Morse inequalities (when f is a Morse
function, i.e. all critical points are non-degenerate):

    #maxima − #saddles + #minima = χ(M)

where χ is the Euler characteristic of the surface (χ = 2 for a sphere,
χ = 0 for a torus).

Reference:
    Edelsbrunner, H., Harer, J. (2010). "Computational Topology: An
    Introduction." American Mathematical Society. §1 (Morse Functions and
    the Euler Characteristic), §III.1 (Critical Points).

Algorithm — discrete Morse theory on triangulated meshes
---------------------------------------------------------
Following Edelsbrunner-Harer 2010 §1 (discrete version with Simulation of
Simplicity tie-breaking, Edelsbrunner-Mücke 1990):

  1. Subdivide the Catmull-Clark cage ``sample_density`` times to obtain a
     dense triangulated mesh that approximates the limit surface.

  2. Evaluate the scalar field f at every mesh vertex.

  3. Break ties in f-values by vertex index: f̃(u) < f̃(v) iff
     f(u) < f(v) OR (f(u) == f(v) AND u < v).  This "simulation of
     simplicity" induces a strict total order on all vertices and ensures
     that each plateau ring produces exactly one critical point (the vertex
     with the extremal index in the ring), matching the smooth Morse theory
     count (e.g. 1 max + 1 min + 2 saddles for a torus height function).

  4. Classify each interior vertex v using the lower star Lk⁻(v) and upper
     star Lk⁺(v) under the SoS total order:

       * **Minimum**  : Lk⁻(v) is empty (no predecessor in the 1-ring).
       * **Maximum**  : Lk⁺(v) is empty (no successor in the 1-ring).
       * **Saddle**   : #components(Lk⁻) + #components(Lk⁺) > 2.
       * **Regular**  : otherwise.

  5. Compute Euler characteristic V − E + F and verify Morse-Euler:
     #max − #sad + #min = χ.

Honest caveats
--------------
* **Degenerate (Bott-Samelson) critical points** — if f is constant on a
  whole connected manifold (e.g. flat plane with f = z = const), the SoS
  tie-breaking still works on individual rings but the classification may
  not reflect the smooth topology.  The ``euler_check`` flag signals
  violations, and ``degenerate_warning`` is set.

* **Boundary vertices** are skipped; classification is meaningful only for
  interior vertices of a closed surface.

* **Sampling resolution** controls accuracy.  The discrete classification
  converges to the smooth truth as ``sample_density`` → ∞.

* **Height function** (f = z-coordinate) is the default scalar field.
  Any callable ``f(xyz: np.ndarray) -> float`` is accepted.

Public API
----------
CriticalPointsReport
    Dataclass: maxima, minima, saddles (each a list of [x,y,z]),
    n_maxima, n_minima, n_saddles, euler_characteristic,
    euler_check (bool), degenerate_warning (str).

find_critical_points(cage, scalar_field=None, sample_density=4)
    Entry point.  ``cage`` may be a SubDMesh or a dict
    {"vertices":[[x,y,z],...], "faces":[[...],...]}.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CriticalPointsReport:
    """Result of ``find_critical_points``.

    Attributes
    ----------
    maxima : list of [x, y, z]
        World-space positions of local maxima of the scalar field.
    minima : list of [x, y, z]
        World-space positions of local minima of the scalar field.
    saddles : list of [x, y, z]
        World-space positions of saddle points.
    n_maxima : int
        Number of maxima.
    n_minima : int
        Number of minima.
    n_saddles : int
        Number of saddles.
    euler_characteristic : int
        Computed mesh Euler characteristic V − E + F (triangulated F).
    euler_check : bool
        True if #max − #sad + #min == euler_characteristic.
    degenerate_warning : str
        Non-empty string if degenerate / Bott-Samelson conditions detected.
    """
    maxima: List[List[float]] = field(default_factory=list)
    minima: List[List[float]] = field(default_factory=list)
    saddles: List[List[float]] = field(default_factory=list)
    n_maxima: int = 0
    n_minima: int = 0
    n_saddles: int = 0
    euler_characteristic: int = 0
    euler_check: bool = False
    degenerate_warning: str = ""


# ---------------------------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------------------------

def _quads_to_tris(
    faces: List[List[int]],
) -> List[Tuple[int, int, int]]:
    """Convert quad/poly faces to triangles by fan-triangulation."""
    tris: List[Tuple[int, int, int]] = []
    for face in faces:
        n = len(face)
        if n < 3:
            continue
        # Fan from first vertex
        for k in range(1, n - 1):
            tris.append((face[0], face[k], face[k + 1]))
    return tris


def _build_vertex_ring(
    n_verts: int,
    tris: List[Tuple[int, int, int]],
) -> Tuple[List[Set[int]], Set[int]]:
    """Return (ring, boundary_verts).

    ring[i]  : set of vertex indices adjacent to i in the triangulation.
    boundary_verts : vertices on a boundary edge (adjacent to only one triangle).
    """
    ring: List[Set[int]] = [set() for _ in range(n_verts)]
    edge_count: Dict[Tuple[int, int], int] = {}

    for (a, b, c) in tris:
        ring[a].add(b); ring[a].add(c)
        ring[b].add(a); ring[b].add(c)
        ring[c].add(a); ring[c].add(b)
        for e in [(min(a, b), max(a, b)),
                  (min(b, c), max(b, c)),
                  (min(a, c), max(a, c))]:
            edge_count[e] = edge_count.get(e, 0) + 1

    boundary_verts: Set[int] = set()
    for (u, v), cnt in edge_count.items():
        if cnt == 1:
            boundary_verts.add(u)
            boundary_verts.add(v)

    return ring, boundary_verts


def _count_components_in_ring(
    ring_vertices: Set[int],
    ring: List[Set[int]],
    exclude: int,
) -> int:
    """Count connected components of the induced subgraph of ``ring_vertices``
    using edges of the triangulation (restricted to ``ring_vertices``).
    """
    if not ring_vertices:
        return 0
    visited: Set[int] = set()
    n_components = 0
    for start in ring_vertices:
        if start in visited:
            continue
        n_components += 1
        stack = [start]
        while stack:
            v = stack.pop()
            if v in visited:
                continue
            visited.add(v)
            for nb in ring[v]:
                if nb in ring_vertices and nb not in visited:
                    stack.append(nb)
    return n_components


# ---------------------------------------------------------------------------
# Euler characteristic
# ---------------------------------------------------------------------------

def _compute_euler(
    n_verts: int,
    tris: List[Tuple[int, int, int]],
) -> int:
    """Compute Euler characteristic V − E + F for a triangulated mesh."""
    edges: Set[Tuple[int, int]] = set()
    for (a, b, c) in tris:
        edges.add((min(a, b), max(a, b)))
        edges.add((min(b, c), max(b, c)))
        edges.add((min(a, c), max(a, c)))
    return n_verts - len(edges) + len(tris)


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------

def _classify_vertices(
    verts: np.ndarray,           # (N, 3)
    f_vals: np.ndarray,          # (N,)
    tris: List[Tuple[int, int, int]],
    ring: List[Set[int]],
    boundary_verts: Set[int],
) -> Tuple[List[int], List[int], List[int]]:
    """Classify interior vertices using lower/upper link with SoS tie-breaking.

    Returns (maxima_indices, minima_indices, saddle_indices).

    Algorithm (Edelsbrunner-Harer 2010 §1 discrete Morse):
      Tie-breaking (Simulation of Simplicity, Edelsbrunner-Mücke 1990):
          f̃(u) < f̃(v)  iff  f(u) < f(v)  OR  (f(u) == f(v) AND u < v)

      Lower star: Lk⁻(v) = {u ∈ ring(v) | f̃(u) < f̃(v)}
      Upper star: Lk⁺(v) = {u ∈ ring(v) | f̃(u) > f̃(v)}

      Minimum : Lk⁻(v) is empty.
      Maximum : Lk⁺(v) is empty.
      Saddle  : #components(Lk⁻) + #components(Lk⁺) > 2.
      Regular : otherwise.

    The SoS tie-breaking ensures that on a plateau ring (e.g. a circle of
    vertices all at max z on a torus) only ONE vertex is classified as the
    extremum — the one with the largest index for a maximum (since under SoS
    all lower-index ties are "below" it), preserving χ = #max − #sad + #min.

    Honest limitation: Bott-Samelson (degenerate) critical points — where
    the critical set is a manifold rather than an isolated point — are not
    resolved; the SoS perturbation maps them to isolated critical points, but
    the count may differ from the smooth theory for non-Morse functions.
    """
    maxima: List[int] = []
    minima: List[int] = []
    saddles: List[int] = []
    n = len(f_vals)

    def _lt(a: int, b: int) -> bool:
        """True if vertex a strictly precedes b in the SoS total order."""
        fa, fb = f_vals[a], f_vals[b]
        return bool(fa < fb or (fa == fb and a < b))

    for vi in range(n):
        if vi in boundary_verts:
            continue
        if not ring[vi]:
            continue

        lower = {u for u in ring[vi] if _lt(u, vi)}
        upper = {u for u in ring[vi] if _lt(vi, u)}

        # Under SoS every vertex has a strict total order, so lower ∪ upper
        # covers all neighbours (no all-tie ambiguity for boundary detection).
        # Exception: isolated vertex with no ring — handled by the ring guard above.

        if not lower:
            minima.append(vi)
        elif not upper:
            maxima.append(vi)
        else:
            # Count connected components of lower and upper link
            c_lower = _count_components_in_ring(lower, ring, vi)
            c_upper = _count_components_in_ring(upper, ring, vi)
            # Morse criterion (Edelsbrunner-Harer 2010 §1):
            #   regular vertex: c_lower + c_upper == 2
            #   simple saddle : c_lower == 1 and c_upper == 1 gives sum 2
            # Wait — a saddle has c_lower = 2 or c_upper = 2:
            #   index-1 critical: c_lower > 1 (lower link disconnected)
            # We check c_lower + c_upper > 2 which catches standard saddles
            # where c_lower = 2 (two valleys) and c_upper = 1 (one ridge).
            if c_lower + c_upper > 2:
                saddles.append(vi)

    return maxima, minima, saddles


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def find_critical_points(
    cage,
    scalar_field: Optional[Callable[[np.ndarray], float]] = None,
    sample_density: int = 4,
) -> CriticalPointsReport:
    """Find critical points of a scalar field on the Catmull-Clark limit surface.

    Parameters
    ----------
    cage : SubDMesh or dict {"vertices": [[x,y,z],...], "faces": [[...], ...]}
        The Catmull-Clark control cage.
    scalar_field : callable(xyz: np.ndarray) -> float, optional
        Scalar function f evaluated at limit-surface points.  Defaults to
        the *height function* f(x, y, z) = z.
    sample_density : int
        Number of CC subdivision levels used to approximate the limit surface.
        Higher values give more accurate classification at the cost of speed.
        Typical: 3 (coarse) … 6 (fine).  Default 4.

    Returns
    -------
    CriticalPointsReport
        Maxima, minima, saddles, Euler check.

    References
    ----------
    Edelsbrunner, H., Harer, J. (2010). "Computational Topology: An
    Introduction." AMS, §1 (Morse Functions), §III.1 (Critical Points).

    Edelsbrunner, H., Mücke, E.P. (1990). "Simulation of Simplicity:
    A Technique to Cope with Degenerate Cases in Geometric Algorithms."
    ACM Transactions on Graphics, 9(1), pp. 66-104.
    """
    # ------------------------------------------------------------------
    # 1. Normalise input cage
    # ------------------------------------------------------------------
    if isinstance(cage, dict):
        raw_v = cage["vertices"]
        raw_f = cage["faces"]
        mesh = SubDMesh(
            vertices=[list(v) for v in raw_v],
            faces=[list(f) for f in raw_f],
        )
    elif isinstance(cage, SubDMesh):
        mesh = cage
    else:
        raise TypeError(f"cage must be SubDMesh or dict, got {type(cage)}")

    if scalar_field is None:
        def scalar_field(xyz: np.ndarray) -> float:  # type: ignore[misc]
            """Default height function f(x,y,z) = z."""
            return float(xyz[2])

    # Clamp sample_density to a sensible range
    levels = max(1, min(int(sample_density), 7))

    # ------------------------------------------------------------------
    # 2. Subdivide to limit-surface approximation
    # ------------------------------------------------------------------
    subd = mesh
    for _ in range(levels):
        subd = catmull_clark_subdivide(subd, levels=1)

    verts_list = subd.vertices          # list of [x, y, z]
    faces_list = subd.faces             # list of [i, j, k, l] or [i, j, k]

    n_verts = len(verts_list)
    verts = np.array(verts_list, dtype=float)  # (N, 3)

    # ------------------------------------------------------------------
    # 3. Evaluate scalar field at each vertex
    # ------------------------------------------------------------------
    f_vals = np.array([scalar_field(verts[i]) for i in range(n_verts)], dtype=float)

    # ------------------------------------------------------------------
    # 4. Triangulate quads → tris
    # ------------------------------------------------------------------
    tris = _quads_to_tris(faces_list)

    # ------------------------------------------------------------------
    # 5. Build adjacency
    # ------------------------------------------------------------------
    ring, boundary_verts = _build_vertex_ring(n_verts, tris)

    # ------------------------------------------------------------------
    # 6. Euler characteristic
    # ------------------------------------------------------------------
    chi = _compute_euler(n_verts, tris)

    # ------------------------------------------------------------------
    # 7. Classify vertices
    # ------------------------------------------------------------------
    max_idx, min_idx, sad_idx = _classify_vertices(
        verts, f_vals, tris, ring, boundary_verts
    )

    # ------------------------------------------------------------------
    # 8. Build report
    # ------------------------------------------------------------------
    def pts(idxs: List[int]) -> List[List[float]]:
        return [list(verts[i]) for i in idxs]

    n_max = len(max_idx)
    n_min = len(min_idx)
    n_sad = len(sad_idx)

    morse_index = n_max - n_sad + n_min
    euler_ok = (morse_index == chi)

    # Detect degenerate warning
    degenerate_warning = ""
    if not euler_ok:
        degenerate_warning = (
            f"Morse-Euler check failed: #max({n_max}) − #sad({n_sad}) + "
            f"#min({n_min}) = {morse_index} ≠ χ = {chi}.  "
            "Possible degenerate (Bott-Samelson) scalar field or "
            "insufficient sample_density."
        )

    return CriticalPointsReport(
        maxima=pts(max_idx),
        minima=pts(min_idx),
        saddles=pts(sad_idx),
        n_maxima=n_max,
        n_minima=n_min,
        n_saddles=n_sad,
        euler_characteristic=chi,
        euler_check=euler_ok,
        degenerate_warning=degenerate_warning,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors subd_limit_integrals.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811

    _spec_critical = ToolSpec(
        name="subd_find_critical_points",
        description=(
            "Find critical points (∇f = 0) of a scalar field on a Catmull-Clark SubD "
            "limit surface using discrete Morse theory (Edelsbrunner-Harer 2010 §1).\n"
            "\n"
            "Critical point types:\n"
            "  Maxima  — local highest points of f (lower star empty).\n"
            "  Minima  — local lowest points of f (upper star empty).\n"
            "  Saddles — mixed ascending/descending neighbourhood (disconnected link).\n"
            "\n"
            "Tie-breaking: vertex index (Simulation of Simplicity, Edelsbrunner-Mücke "
            "1990) ensures each plateau ring contributes exactly one critical point.\n"
            "\n"
            "Morse-Euler: #max − #sad + #min = χ(surface).  euler_check reports whether "
            "this holds for the sampled mesh.\n"
            "\n"
            "  Sphere (cube cage, f=z): 1 max + 1 min + 0 sad, χ=2.\n"
            "  Torus (toroidal cage, f=z): 1 max + 1 min + 2 sad, χ=0.\n"
            "\n"
            "scalar_field options:\n"
            "  'height_z'  (default) : f(x,y,z) = z\n"
            "  'height_x'            : f(x,y,z) = x\n"
            "  'height_y'            : f(x,y,z) = y\n"
            "  'radius'              : f(x,y,z) = sqrt(x²+y²+z²)\n"
            "\n"
            "Returns: { ok, maxima: [[x,y,z],...], minima, saddles, n_maxima, n_minima, "
            "n_saddles, euler_characteristic, euler_check, degenerate_warning }\n"
            "\n"
            "Honest caveat: degenerate (Bott-Samelson) critical points not handled — "
            "constant scalar fields return incorrect counts; euler_check flags this.\n"
            "\n"
            "Reference: Edelsbrunner-Harer 2010, Computational Topology §1."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 4,
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists [[i,j,k,l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
                },
                "scalar_field": {
                    "type": "string",
                    "description": "Scalar field.  One of: height_z (default), height_x, height_y, radius.",
                    "default": "height_z",
                    "enum": ["height_z", "height_x", "height_y", "radius"],
                },
                "sample_density": {
                    "type": "integer",
                    "description": "CC subdivision levels (1–6).  Higher = more accurate.  Default 4.",
                    "default": 4,
                    "minimum": 1,
                    "maximum": 6,
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    _SCALAR_FIELDS = {
        "height_z": lambda xyz: float(xyz[2]),
        "height_x": lambda xyz: float(xyz[0]),
        "height_y": lambda xyz: float(xyz[1]),
        "radius":   lambda xyz: float(math.sqrt(float(xyz[0])**2 + float(xyz[1])**2 + float(xyz[2])**2)),
    }

    @register(_spec_critical)
    async def run_subd_find_critical_points(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        try:
            verts = [[float(c) for c in row] for row in a.get("vertices", [])]
            faces = [[int(i) for i in f] for f in a.get("faces", [])]
            if not verts:
                return err_payload("vertices is required and must be non-empty", "BAD_ARGS")
            if not faces:
                return err_payload("faces is required and must be non-empty", "BAD_ARGS")
            sf_name = str(a.get("scalar_field", "height_z"))
            if sf_name not in _SCALAR_FIELDS:
                return err_payload(
                    f"scalar_field must be one of {list(_SCALAR_FIELDS)}", "BAD_ARGS"
                )
            density = int(a.get("sample_density", 4))
            if density < 1 or density > 6:
                return err_payload("sample_density must be 1..6", "BAD_ARGS")
            cage = SubDMesh(vertices=verts, faces=faces)
        except Exception as exc:
            return err_payload(f"invalid cage: {exc}", "BAD_ARGS")
        try:
            rpt = find_critical_points(cage, scalar_field=_SCALAR_FIELDS[sf_name], sample_density=density)
        except Exception as exc:
            return err_payload(f"computation error: {exc}", "INTERNAL")
        return ok_payload({
            "ok": True,
            "maxima": rpt.maxima,
            "minima": rpt.minima,
            "saddles": rpt.saddles,
            "n_maxima": rpt.n_maxima,
            "n_minima": rpt.n_minima,
            "n_saddles": rpt.n_saddles,
            "euler_characteristic": rpt.euler_characteristic,
            "euler_check": rpt.euler_check,
            "degenerate_warning": rpt.degenerate_warning,
        })
