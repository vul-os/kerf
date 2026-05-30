"""B-rep Euler-Poincaré topology verifier.

Implements the full generalised Euler-Poincaré formula for B-rep solids::

    V - E + F - H = 2 * (S - G)

equivalently::

    χ  =  V - E + F  =  2(S - G) + H

where:

  * V  = number of distinct vertices
  * E  = number of distinct edges
  * F  = number of faces
  * H  = number of *ring* (inner/hole) loops — every face contributes one
         mandatory outer loop; every additional loop on a face is a ring loop
  * S  = number of shells (connected sets of faces)
  * G  = genus (topological handles / through-holes; sphere G=0, torus G=1)

For a **single closed solid with no through-holes and no inner loops**
(e.g. a unit cube or a sphere):

    V - E + F = 2   (Euler characteristic χ = 2)

For a **solid torus** (genus 1, no inner loops):

    V - E + F = 0   (χ = 0)

References
----------
* Mantyla, M. (1988). *An Introduction to Solid Modeling*, §6 "Euler Operators
  and the Euler-Poincaré Formula". Computer Science Press.
* Hoffmann, C.M. (1989). *Geometric and Solid Modeling: An Introduction*, §5
  "Topology and the Euler Formula". Morgan Kaufmann.

CAVEATS / HONESTY FLAGS
-----------------------
1. **Genus estimation from mesh connectivity**: When a ``Body`` object from
   ``kerf_cad_core.geom.brep`` is supplied, genus G is derived from the per-
   shell Euler characteristic of *closed* shells.  This is exact for manifold
   solids.  Open shells and degenerate (self-touching) shells report G=0.
2. **Vertex deduplication**: V is counted as distinct ``Vertex`` *objects* in
   the B-rep graph — if the modelling kernel created duplicate ``Vertex``
   instances for the same geometric point (e.g. after a sew/heal operation
   without topological merging) then V will be over-counted and the formula
   will appear to fail.  The report flags this via ``degenerate_vertices_hint``
   when ``V - E + F`` is not an even integer.
3. **dict-based input**: The ``verify_euler_topology_from_dict`` path accepts
   the same face-list schema as ``brep_inspect_connectivity``.  Edge topology
   is inferred from ``(start, end)`` vertex labels.  Genus G **cannot** be
   inferred from this representation without additional shell/genus hints
   supplied by the caller.  Pass ``genus_hint`` and ``shells_hint`` for non-
   trivial solids.
4. **Ring loops from dict**: Inner/hole loops cannot be distinguished from the
   flat face-edge list.  Pass ``inner_loops_hint`` if the solid has faces with
   inner loops (cutouts, counterbores, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# EulerCheckReport
# ---------------------------------------------------------------------------

@dataclass
class EulerCheckReport:
    """Full Euler-Poincaré audit result.

    Attributes
    ----------
    V : int
        Vertex count.
    E : int
        Edge count.
    F : int
        Face count.
    S : int
        Shell count (connected face-sets).
    H : int
        Ring / inner-loop count (total loops − F).
    G : int
        Genus (topological handles; 0 = sphere-like, 1 = torus-like).
    actual_chi : int
        Computed χ = V − E + F.
    expected_chi : int
        Expected χ = 2*(S − G) + H  (right-hand side of Euler-Poincaré).
    valid : bool
        ``True`` iff ``actual_chi == expected_chi``.
    violations : list[str]
        Human-readable descriptions of any formula violations or warnings.
    degenerate_vertices_hint : bool
        ``True`` when V − E + F is not an even integer (possible vertex
        duplication after sew/heal; see module docstring caveat 2).
    """

    V: int = 0
    E: int = 0
    F: int = 0
    S: int = 1
    H: int = 0
    G: int = 0
    actual_chi: int = 0
    expected_chi: int = 2
    valid: bool = False
    violations: List[str] = field(default_factory=list)
    degenerate_vertices_hint: bool = False

    def as_dict(self) -> dict:
        return {
            "V": self.V,
            "E": self.E,
            "F": self.F,
            "S": self.S,
            "H": self.H,
            "G": self.G,
            "actual_chi": self.actual_chi,
            "expected_chi": self.expected_chi,
            "valid": self.valid,
            "violations": self.violations,
            "degenerate_vertices_hint": self.degenerate_vertices_hint,
        }


# ---------------------------------------------------------------------------
# verify_euler_topology — Body-object path
# ---------------------------------------------------------------------------

def verify_euler_topology(body: object) -> EulerCheckReport:
    """Verify the Euler-Poincaré formula for a ``Body`` B-rep object.

    Accepts a ``kerf_cad_core.geom.brep.Body`` (or any object exposing the
    same ``all_vertices()``, ``all_edges()``, ``all_faces()``,
    ``all_shells()``, and ``genus()`` accessors).

    Parameters
    ----------
    body :
        A ``Body`` instance from ``kerf_cad_core.geom.brep``.

    Returns
    -------
    EulerCheckReport
        Full formula audit.  ``report.valid`` is ``True`` for a
        topologically consistent B-rep.

    References
    ----------
    Mantyla 1988 §6; Hoffmann 1989 §5.
    """
    report = EulerCheckReport()

    try:
        V = len(body.all_vertices())
        E = len(body.all_edges())
        faces = body.all_faces()
        F = len(faces)
        shells = body.all_shells()
        S = len(shells)
        # Total loops minus one per face = ring loops
        total_loops = sum(len(f.loops) for f in faces)
        H = total_loops - F
        G = body.genus() if hasattr(body, "genus") else 0
    except Exception as exc:
        report.violations.append(f"Could not traverse B-rep graph: {exc}")
        return report

    actual_chi = V - E + F
    expected_chi = 2 * (S - G) + H

    report.V = V
    report.E = E
    report.F = F
    report.S = S
    report.H = H
    report.G = G
    report.actual_chi = actual_chi
    report.expected_chi = expected_chi

    # Odd chi may indicate vertex duplication (caveat 2)
    report.degenerate_vertices_hint = (actual_chi % 2) != 0

    violations: List[str] = []

    if actual_chi != expected_chi:
        violations.append(
            f"Euler-Poincaré violated: V-E+F={actual_chi} but "
            f"2*(S-G)+H = 2*({S}-{G})+{H} = {expected_chi}"
        )

    if V < 0 or E < 0 or F < 0:
        violations.append("Negative count (V/E/F) — corrupt topology graph.")

    if S == 0 and F > 0:
        violations.append(
            "Zero shells but faces exist — unparented face(s) detected."
        )

    if H < 0:
        violations.append(
            f"Negative ring-loop count H={H} — more faces than loops, "
            "which is impossible (every face needs at least one loop)."
        )

    if G < 0:
        violations.append(f"Negative genus G={G} — corrupt Euler bookkeeping.")

    if report.degenerate_vertices_hint and not violations:
        violations.append(
            "WARN: V-E+F is odd.  Possible vertex deduplication issue "
            "(see topology_euler_check module docstring, caveat 2)."
        )

    report.violations = violations
    report.valid = (actual_chi == expected_chi) and (H >= 0) and (G >= 0)
    return report


# ---------------------------------------------------------------------------
# verify_euler_topology_from_dict — dict / JSON path
# ---------------------------------------------------------------------------

def verify_euler_topology_from_dict(
    faces: List[Dict],
    *,
    genus_hint: int = 0,
    shells_hint: Optional[int] = None,
    inner_loops_hint: int = 0,
) -> EulerCheckReport:
    """Verify Euler-Poincaré from a face-list dict (JSON-serialisable input).

    Uses the same schema as ``brep_inspect_connectivity``::

        faces = [
            {
                "face_id": "f0",
                "edges": [
                    {"edge_id": "e0", "start": "v0", "end": "v1"},
                    ...
                ]
            },
            ...
        ]

    Parameters
    ----------
    faces :
        Face list with edges, each edge having ``edge_id``, ``start``,
        ``end`` vertex labels.
    genus_hint : int
        Caller-supplied genus G.  Cannot be inferred from the flat face list
        alone (default 0; pass 1 for a torus, etc.).  See module docstring
        caveat 3.
    shells_hint : int, optional
        Caller-supplied shell count S.  If ``None``, computed via union-find
        on edge adjacency.
    inner_loops_hint : int
        Number of inner/ring loops H.  Cannot be inferred from the flat
        face-edge list (default 0).  See module docstring caveat 4.

    Returns
    -------
    EulerCheckReport

    References
    ----------
    Mantyla 1988 §6; Hoffmann 1989 §5.
    """
    report = EulerCheckReport()

    if not isinstance(faces, list):
        report.violations.append("'faces' must be a list.")
        return report

    # -- count unique vertices and edges ------------------------------------
    vertices: Set[object] = set()
    edges: Set[object] = set()
    F = len(faces)

    for face in faces:
        for edge in face.get("edges", []):
            eid = edge.get("edge_id")
            if eid is not None:
                edges.add(eid)
            v0 = edge.get("start")
            v1 = edge.get("end")
            if v0 is not None:
                vertices.add(v0)
            if v1 is not None:
                vertices.add(v1)

    V = len(vertices)
    E = len(edges)

    # -- shells via union-find on edge adjacency ----------------------------
    if shells_hint is not None:
        S = shells_hint
    else:
        S = _count_shells_union_find(faces, F)

    G = genus_hint
    H = inner_loops_hint

    actual_chi = V - E + F
    expected_chi = 2 * (S - G) + H

    report.V = V
    report.E = E
    report.F = F
    report.S = S
    report.H = H
    report.G = G
    report.actual_chi = actual_chi
    report.expected_chi = expected_chi
    report.degenerate_vertices_hint = (actual_chi % 2) != 0

    violations: List[str] = []

    if actual_chi != expected_chi:
        violations.append(
            f"Euler-Poincaré violated: V-E+F={actual_chi} but "
            f"2*(S-G)+H = 2*({S}-{G})+{H} = {expected_chi}"
        )

    if F == 0:
        violations.append("No faces — empty solid.")

    if H < 0:
        violations.append(f"Negative inner_loops_hint H={H}.")

    if G < 0:
        violations.append(f"Negative genus_hint G={G}.")

    report.violations = violations
    report.valid = (actual_chi == expected_chi) and (H >= 0) and (G >= 0) and (F > 0)
    return report


# ---------------------------------------------------------------------------
# Union-find shell counter (identical edge-sharing adjacency)
# ---------------------------------------------------------------------------

def _count_shells_union_find(faces: List[Dict], F: int) -> int:
    """Count connected shell components via union-find on shared edges.

    Two faces are in the same shell if they share at least one edge.
    This is the standard Mantyla 1988 §6 shell-adjacency definition.
    """
    if F == 0:
        return 0

    parent = list(range(F))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    # Build edge → face index map
    edge_to_faces: Dict[object, List[int]] = {}
    for i, face in enumerate(faces):
        for edge in face.get("edges", []):
            eid = edge.get("edge_id")
            if eid is not None:
                edge_to_faces.setdefault(eid, []).append(i)

    for face_indices in edge_to_faces.values():
        for k in range(1, len(face_indices)):
            union(face_indices[0], face_indices[k])

    roots = {find(i) for i in range(F)}
    return len(roots)


# ---------------------------------------------------------------------------
# Oracle helpers for unit tests and documentation
# ---------------------------------------------------------------------------

def _make_cube_body():
    """Return a ``Body`` for a unit cube (V=8, E=12, F=6, S=1, G=0, H=0)."""
    from kerf_cad_core.geom.brep import (
        Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Plane, Line3,
    )
    import numpy as np

    # 8 vertices of the unit cube
    corners = [
        np.array([x, y, z], dtype=float)
        for x in (0.0, 1.0)
        for y in (0.0, 1.0)
        for z in (0.0, 1.0)
    ]
    verts = [Vertex(c) for c in corners]

    def vi(x: int, y: int, z: int) -> Vertex:
        return verts[x * 4 + y * 2 + z]

    _edge_cache: Dict = {}

    def _get_edge(va: Vertex, vb: Vertex) -> Edge:
        key = (id(va), id(vb))
        rkey = (id(vb), id(va))
        if key in _edge_cache:
            return _edge_cache[key]
        if rkey in _edge_cache:
            return _edge_cache[rkey]
        e = Edge(Line3(va.point, vb.point), 0.0, 1.0, va, vb)
        _edge_cache[key] = e
        return e

    def _make_face(v0: Vertex, v1: Vertex, v2: Vertex, v3: Vertex, surf) -> Face:
        e01 = _get_edge(v0, v1)
        e12 = _get_edge(v1, v2)
        e23 = _get_edge(v2, v3)
        e30 = _get_edge(v3, v0)

        def _coedge(e: Edge, va: Vertex) -> Coedge:
            return Coedge(e, id(e.v_start) == id(va))

        c0 = _coedge(e01, v0)
        c1 = _coedge(e12, v1)
        c2 = _coedge(e23, v2)
        c3 = _coedge(e30, v3)
        loop = Loop([c0, c1, c2, c3], is_outer=True)
        return Face(surf, [loop])

    v000, v001 = vi(0, 0, 0), vi(0, 0, 1)
    v010, v011 = vi(0, 1, 0), vi(0, 1, 1)
    v100, v101 = vi(1, 0, 0), vi(1, 0, 1)
    v110, v111 = vi(1, 1, 0), vi(1, 1, 1)

    face_defs = [
        (v000, v010, v110, v100,
         Plane(np.array([0, 0, 0], dtype=float), np.array([1, 0, 0], dtype=float), np.array([0, 1, 0], dtype=float))),
        (v001, v101, v111, v011,
         Plane(np.array([0, 0, 1], dtype=float), np.array([1, 0, 0], dtype=float), np.array([0, 1, 0], dtype=float))),
        (v000, v100, v101, v001,
         Plane(np.array([0, 0, 0], dtype=float), np.array([1, 0, 0], dtype=float), np.array([0, 0, 1], dtype=float))),
        (v010, v011, v111, v110,
         Plane(np.array([0, 1, 0], dtype=float), np.array([1, 0, 0], dtype=float), np.array([0, 0, 1], dtype=float))),
        (v000, v001, v011, v010,
         Plane(np.array([0, 0, 0], dtype=float), np.array([0, 0, 1], dtype=float), np.array([0, 1, 0], dtype=float))),
        (v100, v110, v111, v101,
         Plane(np.array([1, 0, 0], dtype=float), np.array([0, 0, 1], dtype=float), np.array([0, 1, 0], dtype=float))),
    ]

    face_objs = [_make_face(v0, v1, v2, v3, surf) for v0, v1, v2, v3, surf in face_defs]
    shell = Shell(face_objs, is_closed=True)
    solid = Solid([shell])
    return Body(solids=[solid])


def _make_torus_body():
    """Return the canonical B-rep torus using ``make_torus`` from brep.py.

    The canonical Mantyla torus (1988 §6.2) has a *single* face bounded by
    the commutator loop [a, b] = a b a⁻¹ b⁻¹ (major × minor seam).
    Counts: V=1, E=2, F=1, L=1, H=0, S=1, G=1.

    Verification: V-E+F-H-2*(S-G) = 1-2+1-0-2*(1-1) = 0 ✓
    Equivalently via verify_euler_topology:
        actual_chi = V-E+F = 0
        expected_chi = 2*(S-G)+H = 0
        valid = True

    Body.genus() computes per-shell chi = V_s-E_s+F_s-H_s = 1-2+1-0 = 0
    → genus = (2-0)//2 = 1 ✓

    See Mantyla 1988 §6.2 and Hoffmann 1989 §5.1.
    """
    from kerf_cad_core.geom.brep import make_torus
    return make_torus(major_radius=2.0, minor_radius=0.5)


def _make_disjoint_cubes_body():
    """Return a ``Body`` with two disconnected unit cubes (S=2, χ=4)."""
    from kerf_cad_core.geom.brep import Body

    cube1 = _make_cube_body()
    cube2 = _make_cube_body()
    all_solids = list(cube1.solids) + list(cube2.solids)
    return Body(solids=all_solids)
