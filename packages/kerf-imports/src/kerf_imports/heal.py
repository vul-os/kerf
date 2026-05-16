"""
heal.py — geometry healing for B-rep-like / triangle-mesh models.

Mesh format (same as mesh.py):
  {
    "version": 1,
    "vertices": [[x, y, z], ...],
    "indices":  [i0, i1, i2, ...],   // triangle list; every 3 = one face
  }

Pipeline entry point:
  heal(model, tolerance)  →  dict with keys: model, report

Standalone validators / parsers:
  validate_watertight(model)          →  {"watertight": bool, "issues": [...]}
  step_ap242_metadata(step_text)      →  {"product": ..., "has_gdt": bool, ...}
  interop_report(model)               →  {"ready": bool, "issues": [...]}

LLM tools registered via @register mirror the mesh.py convention.
All functions return dicts and never raise — errors surface as
{"ok": False, "reason": "..."}.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections import defaultdict, deque
from typing import Any, Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx


# ─── Vector helpers ───────────────────────────────────────────────────────────

def _sub(a, b):   return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]
def _add(a, b):   return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]
def _scale(a, s): return [a[0]*s, a[1]*s, a[2]*s]
def _dot(a, b):   return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def _cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def _len(v):      return math.sqrt(v[0]**2+v[1]**2+v[2]**2)
def _norm(v):
    l = _len(v)
    return [v[0]/l, v[1]/l, v[2]/l] if l > 1e-12 else [0.0, 0.0, 0.0]


# ─── Internal mesh helpers ────────────────────────────────────────────────────

def _face_count(model: dict) -> int:
    return len(model.get("indices", [])) // 3


def _face_triple(model: dict, f: int) -> tuple[int, int, int]:
    idx = model["indices"]
    return idx[f*3], idx[f*3+1], idx[f*3+2]


def _face_area(verts, a, b, c) -> float:
    va, vb, vc = verts[a], verts[b], verts[c]
    return _len(_cross(_sub(vb, va), _sub(vc, va))) * 0.5


def _face_normal(verts, a, b, c):
    return _norm(_cross(_sub(verts[b], verts[a]), _sub(verts[c], verts[a])))


def _build_edge_map(indices: list[int]) -> dict[str, list[int]]:
    """Undirected edge key → list of face indices."""
    em: dict[str, list[int]] = {}
    nf = len(indices) // 3
    for f in range(nf):
        a, b, c = indices[f*3], indices[f*3+1], indices[f*3+2]
        for u, v in ((a, b), (b, c), (c, a)):
            key = f"{min(u,v)}:{max(u,v)}"
            em.setdefault(key, []).append(f)
    return em


def _build_directed_edge_map(indices: list[int]) -> dict[str, int]:
    """Directed half-edge (u→v) → face index."""
    hm: dict[str, int] = {}
    nf = len(indices) // 3
    for f in range(nf):
        a, b, c = indices[f*3], indices[f*3+1], indices[f*3+2]
        for u, v in ((a, b), (b, c), (c, a)):
            hm[f"{u}:{v}"] = f
    return hm


def _euler_characteristic(n_verts: int, n_edges: int, n_faces: int) -> int:
    return n_verts - n_edges + n_faces


# ─── Step 1: stitch small gaps (merge vertices within tolerance) ──────────────

def _stitch_vertices(model: dict, tol: float) -> tuple[dict, int]:
    """
    Merge vertices within *tol* of each other (snap-weld).
    Returns updated model and the number of vertices merged.
    """
    verts = model["vertices"]
    indices = list(model["indices"])
    tol2 = tol * tol
    n = len(verts)
    weld = list(range(n))

    new_verts: list[list[float]] = []
    remap = [-1] * n

    for i, v in enumerate(verts):
        found = -1
        for j, w in enumerate(new_verts):
            dx, dy, dz = v[0]-w[0], v[1]-w[1], v[2]-w[2]
            if dx*dx + dy*dy + dz*dz <= tol2:
                found = j
                break
        if found == -1:
            found = len(new_verts)
            new_verts.append(list(v))
        remap[i] = found

    merged = n - len(new_verts)

    new_indices = []
    for k in range(len(indices) // 3):
        a, b, c = remap[indices[k*3]], remap[indices[k*3+1]], remap[indices[k*3+2]]
        if a == b or b == c or a == c:
            continue
        new_indices += [a, b, c]

    out = {**model, "vertices": new_verts, "indices": new_indices}
    return out, merged


# ─── Step 2: remove sliver faces ─────────────────────────────────────────────

def _remove_sliver_faces(model: dict, tol: float) -> tuple[dict, int]:
    """
    Remove faces whose area is below *tol*^2 / 2  (i.e., shorter than tol).
    Uses tol*tol as the area threshold (conservative).
    """
    verts = model["vertices"]
    indices = model["indices"]
    nf = len(indices) // 3
    area_thresh = tol * tol * 0.5
    new_indices = []
    removed = 0
    for f in range(nf):
        a, b, c = indices[f*3], indices[f*3+1], indices[f*3+2]
        if _face_area(verts, a, b, c) < area_thresh:
            removed += 1
        else:
            new_indices += [a, b, c]
    return {**model, "indices": new_indices}, removed


# ─── Step 3: merge tiny edges ─────────────────────────────────────────────────

def _merge_tiny_edges(model: dict, tol: float) -> tuple[dict, int]:
    """
    Collapse edges shorter than *tol* by merging the two endpoint vertices.
    Returns updated model and count of edges collapsed.
    """
    verts = [list(v) for v in model["vertices"]]
    indices = list(model["indices"])
    tol2 = tol * tol
    remap = list(range(len(verts)))
    collapsed = 0

    def canonical(i: int) -> int:
        while remap[i] != i:
            remap[i] = remap[remap[i]]
            i = remap[i]
        return i

    nf = len(indices) // 3
    seen: set[tuple[int, int]] = set()
    for f in range(nf):
        for ui, vi in ((0, 1), (1, 2), (2, 0)):
            ai = canonical(indices[f*3+ui])
            bi = canonical(indices[f*3+vi])
            if ai == bi:
                continue
            key = (min(ai, bi), max(ai, bi))
            if key in seen:
                continue
            seen.add(key)
            va, vb = verts[ai], verts[bi]
            dx, dy, dz = va[0]-vb[0], va[1]-vb[1], va[2]-vb[2]
            if dx*dx + dy*dy + dz*dz < tol2:
                mid = _scale(_add(va, vb), 0.5)
                verts[ai] = mid
                remap[bi] = ai
                collapsed += 1

    # compact
    vi_map = [-1] * len(verts)
    new_verts: list[list[float]] = []
    for i in range(len(verts)):
        if canonical(i) == i:
            vi_map[i] = len(new_verts)
            new_verts.append(verts[i])

    new_indices = []
    for f in range(len(indices) // 3):
        a = vi_map[canonical(indices[f*3])]
        b = vi_map[canonical(indices[f*3+1])]
        c = vi_map[canonical(indices[f*3+2])]
        if a < 0 or b < 0 or c < 0 or a == b or b == c or a == c:
            continue
        new_indices += [a, b, c]

    return {**model, "vertices": new_verts, "indices": new_indices}, collapsed


# ─── Step 4: unify face normals (BFS consistent winding) ─────────────────────

def _unify_normals(model: dict) -> tuple[dict, int]:
    """
    Make face winding consistent via BFS.  The reference face is the one
    whose normal has the largest positive Z (or face 0 if degenerate).
    Returns updated model and number of faces flipped.

    Two faces are neighbours if they share an undirected edge.
    - If they share the edge in *opposite* directed directions (u→v and v→u)
      the winding is already consistent: no flip needed.
    - If they share the edge in the *same* directed direction (both u→v)
      the winding is inconsistent: flip the newly-visited neighbour.
    """
    verts = model["vertices"]
    indices = list(model["indices"])
    nf = len(indices) // 3
    if nf == 0:
        return model, 0

    # undirected edge key → list of face indices (to find adjacency)
    undirected: dict[str, list[int]] = {}
    for f in range(nf):
        a, b, c = indices[f*3], indices[f*3+1], indices[f*3+2]
        for u, v in ((a, b), (b, c), (c, a)):
            key = f"{min(u,v)}:{max(u,v)}"
            undirected.setdefault(key, []).append(f)

    # directed half-edge (rebuilt on flips)
    def rebuild_dir(idx):
        d: dict[str, int] = {}
        for fi in range(len(idx) // 3):
            a, b, c = idx[fi*3], idx[fi*3+1], idx[fi*3+2]
            for pu, pv in ((a, b), (b, c), (c, a)):
                d[f"{pu}:{pv}"] = fi
        return d

    dir_edge = rebuild_dir(indices)

    flipped = [False] * nf
    visited = [False] * nf

    # Choose seed: face with largest upward normal
    best_seed, best_nz = 0, -2.0
    for f in range(nf):
        a, b, c = indices[f*3], indices[f*3+1], indices[f*3+2]
        if a == b or b == c or a == c:
            continue
        n = _face_normal(verts, a, b, c)
        if n[2] > best_nz:
            best_nz = n[2]
            best_seed = f

    queue: deque[int] = deque([best_seed])
    visited[best_seed] = True

    while queue:
        f = queue.popleft()
        fa, fb, fc = indices[f*3], indices[f*3+1], indices[f*3+2]
        for u, v in ((fa, fb), (fb, fc), (fc, fa)):
            ukey = f"{min(u,v)}:{max(u,v)}"
            for g in undirected.get(ukey, []):
                if g == f or visited[g]:
                    continue
                visited[g] = True
                # Check winding consistency:
                # face f has directed edge u→v.
                # If face g ALSO has u→v (same direction) → inconsistent → flip g.
                # If face g has v→u (opposite direction) → consistent → no flip.
                if dir_edge.get(f"{u}:{v}") == g:
                    # same direction → flip g
                    flipped[g] = True
                    indices[g*3+1], indices[g*3+2] = indices[g*3+2], indices[g*3+1]
                    # update dir_edge for g's new edges
                    ga, gb, gc = indices[g*3], indices[g*3+1], indices[g*3+2]
                    for pu, pv in ((ga, gb), (gb, gc), (gc, ga)):
                        dir_edge[f"{pu}:{pv}"] = g
                    # remove the old (now-stale) directed edges of g
                    # (the three that were there before the flip)
                    old_a, old_b, old_c = ga, gc, gb  # pre-flip was ga, gc, gb
                    for pu, pv in ((old_a, old_b), (old_b, old_c), (old_c, old_a)):
                        if dir_edge.get(f"{pu}:{pv}") == g:
                            del dir_edge[f"{pu}:{pv}"]
                queue.append(g)

    n_flipped = sum(1 for x in flipped if x)
    return {**model, "indices": indices}, n_flipped


# ─── Step 5: remove duplicate vertices and faces ─────────────────────────────

def _remove_duplicates(model: dict) -> tuple[dict, int, int]:
    """
    Remove exactly-duplicate vertices and duplicate/degenerate faces.
    Returns (model, dup_verts_removed, dup_faces_removed).
    """
    verts = model["vertices"]
    indices = model["indices"]

    # Deduplicate vertices (exact match)
    key_to_idx: dict[tuple, int] = {}
    new_verts: list[list[float]] = []
    remap = [-1] * len(verts)
    dup_v = 0
    for i, v in enumerate(verts):
        k = (v[0], v[1], v[2])
        if k in key_to_idx:
            remap[i] = key_to_idx[k]
            dup_v += 1
        else:
            key_to_idx[k] = len(new_verts)
            remap[i] = len(new_verts)
            new_verts.append(list(v))

    # Deduplicate faces (canonical triple)
    face_set: set[tuple[int, int, int]] = set()
    new_indices = []
    dup_f = 0
    for f in range(len(indices) // 3):
        a, b, c = remap[indices[f*3]], remap[indices[f*3+1]], remap[indices[f*3+2]]
        if a == b or b == c or a == c:
            dup_f += 1
            continue
        canon = tuple(sorted([a, b, c]))
        if canon in face_set:
            dup_f += 1
            continue
        face_set.add(canon)
        new_indices += [a, b, c]

    return {**model, "vertices": new_verts, "indices": new_indices}, dup_v, dup_f


# ─── Step 6: self-intersection detection (flag only) ─────────────────────────

def _detect_self_intersections(model: dict) -> list[tuple[int, int]]:
    """
    Detect pairs of non-adjacent triangles whose bounding boxes overlap
    AND whose vertex sets share no vertex (cheap proxy; not full exact test).
    Returns list of (face_i, face_j) pairs flagged as potential intersections.
    Capped at 100 pairs to avoid O(n²) blowup on large meshes.
    """
    verts = model["vertices"]
    indices = model["indices"]
    nf = len(indices) // 3
    MAX_PAIRS = 100

    # AABB per face
    aabbs = []
    for f in range(nf):
        a, b, c = indices[f*3], indices[f*3+1], indices[f*3+2]
        xs = [verts[a][0], verts[b][0], verts[c][0]]
        ys = [verts[a][1], verts[b][1], verts[c][1]]
        zs = [verts[a][2], verts[b][2], verts[c][2]]
        aabbs.append((min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))

    pairs: list[tuple[int, int]] = []
    for i in range(nf):
        if len(pairs) >= MAX_PAIRS:
            break
        vi = set(indices[i*3:i*3+3])
        xi0, xi1, yi0, yi1, zi0, zi1 = aabbs[i]
        for j in range(i+1, nf):
            if len(pairs) >= MAX_PAIRS:
                break
            vj = set(indices[j*3:j*3+3])
            if vi & vj:  # adjacent or coincident — skip
                continue
            xj0, xj1, yj0, yj1, zj0, zj1 = aabbs[j]
            # AABB overlap check
            if xi1 < xj0 or xj1 < xi0:
                continue
            if yi1 < yj0 or yj1 < yi0:
                continue
            if zi1 < zj0 or zj1 < zi0:
                continue
            pairs.append((i, j))
    return pairs


# ─── Step 7: non-manifold detection ──────────────────────────────────────────

def _detect_non_manifold(model: dict) -> dict[str, list]:
    """
    Detect non-manifold edges (shared by >2 faces) and non-manifold vertices
    (vertex on more than one boundary loop when the mesh should be manifold).
    Returns {"edges": [...], "vertices": [...]}.
    """
    indices = model["indices"]
    verts = model["vertices"]
    nf = len(indices) // 3

    # Edge → face count
    edge_faces: dict[str, list[int]] = {}
    for f in range(nf):
        a, b, c = indices[f*3], indices[f*3+1], indices[f*3+2]
        for u, v in ((a, b), (b, c), (c, a)):
            key = f"{min(u,v)}:{max(u,v)}"
            edge_faces.setdefault(key, []).append(f)

    nm_edges = [key for key, fs in edge_faces.items() if len(fs) > 2]

    # Non-manifold vertices: vertices that appear in non-manifold edges
    nm_verts_set: set[int] = set()
    for key in nm_edges:
        a_s, b_s = key.split(":")
        nm_verts_set.add(int(a_s))
        nm_verts_set.add(int(b_s))

    return {"edges": nm_edges, "vertices": sorted(nm_verts_set)}


# ─── Step 8: fill small holes ─────────────────────────────────────────────────

def _fill_holes(model: dict, max_loop_len: int = 20) -> tuple[dict, int]:
    """
    Fill boundary loops (open holes) with fan triangulation.
    Only fills loops of length <= max_loop_len to avoid filling large openings.
    Returns updated model and number of holes filled.
    """
    verts = [list(v) for v in model["vertices"]]
    indices = list(model["indices"])
    nf = len(indices) // 3

    # Build half-edge → face and find boundary edges
    half_edge: dict[str, int] = _build_directed_edge_map(indices)

    boundary_next: dict[int, int] = {}
    for key, f in half_edge.items():
        a_s, b_s = key.split(":")
        a, b = int(a_s), int(b_s)
        if f"{b}:{a}" not in half_edge:
            boundary_next[b] = a

    visited: set[int] = set()
    loops: list[list[int]] = []
    for start in list(boundary_next.keys()):
        if start in visited:
            continue
        loop: list[int] = []
        cur = start
        safety = len(boundary_next) + 1
        while cur not in visited and safety > 0:
            safety -= 1
            visited.add(cur)
            loop.append(cur)
            cur = boundary_next.get(cur)  # type: ignore[assignment]
            if cur is None:
                break
        if len(loop) >= 3:
            loops.append(loop)

    filled = 0
    for loop in loops:
        if len(loop) > max_loop_len:
            continue
        inv = 1.0 / len(loop)
        cx = sum(verts[vi][0] for vi in loop) * inv
        cy = sum(verts[vi][1] for vi in loop) * inv
        cz = sum(verts[vi][2] for vi in loop) * inv
        ci = len(verts)
        verts.append([cx, cy, cz])
        for i in range(len(loop)):
            a_v = loop[i]
            b_v = loop[(i + 1) % len(loop)]
            indices += [a_v, b_v, ci]
        filled += 1

    return {**model, "vertices": verts, "indices": indices}, filled


# ─── Main heal pipeline ───────────────────────────────────────────────────────

def heal(model: dict, tolerance: float = 1e-4) -> dict:
    """
    Run the full geometry healing pipeline on a triangle-mesh model.

    Steps (in order):
      1. stitch_vertices   — close small gaps (merge within tol)
      2. remove_slivers    — drop faces with area < tol²/2
      3. merge_tiny_edges  — collapse edges shorter than tol
      4. unify_normals     — BFS consistent winding
      5. remove_duplicates — exact-duplicate vertices / faces
      6. self_intersections— flag (do NOT auto-fix)
      7. non_manifold      — detect and report
      8. fill_holes        — fan-fill small boundary loops

    Returns:
      {
        "model": <healed mesh dict>,
        "report": {
          "stitched_vertices": int,
          "sliver_faces_removed": int,
          "tiny_edges_collapsed": int,
          "faces_flipped": int,
          "duplicate_vertices_removed": int,
          "duplicate_faces_removed": int,
          "self_intersection_pairs": int,
          "self_intersection_flagged": [[i,j], ...],
          "non_manifold_edges": int,
          "non_manifold_vertices": int,
          "holes_filled": int,
        }
      }
    """
    try:
        if not isinstance(model, dict):
            return {"ok": False, "reason": "model must be a dict"}
        if "vertices" not in model or "indices" not in model:
            return {"ok": False, "reason": "model must have 'vertices' and 'indices'"}

        tol = float(tolerance)
        m = model

        m, stitched      = _stitch_vertices(m, tol)
        m, slivers       = _remove_sliver_faces(m, tol)
        m, tiny_edges    = _merge_tiny_edges(m, tol)
        m, flipped       = _unify_normals(m)
        m, dup_v, dup_f  = _remove_duplicates(m)
        si_pairs         = _detect_self_intersections(m)
        nm               = _detect_non_manifold(m)
        m, holes_filled  = _fill_holes(m)

        return {
            "model": m,
            "report": {
                "stitched_vertices": stitched,
                "sliver_faces_removed": slivers,
                "tiny_edges_collapsed": tiny_edges,
                "faces_flipped": flipped,
                "duplicate_vertices_removed": dup_v,
                "duplicate_faces_removed": dup_f,
                "self_intersection_pairs": len(si_pairs),
                "self_intersection_flagged": [[i, j] for i, j in si_pairs],
                "non_manifold_edges": len(nm["edges"]),
                "non_manifold_vertices": len(nm["vertices"]),
                "holes_filled": holes_filled,
            },
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ─── Watertight validation ────────────────────────────────────────────────────

def validate_watertight(model: dict) -> dict:
    """
    Check whether *model* is a closed, orientable 2-manifold.

    Tests:
    - Every edge is shared by exactly 2 faces (no boundary, no non-manifold)
    - Euler characteristic V − E + F == 2  (for a genus-0 closed surface)

    Returns:
      {
        "watertight": bool,
        "euler": int,          # V − E + F
        "issues": [str, ...]
      }
    """
    try:
        verts = model.get("vertices", [])
        indices = model.get("indices", [])
        nf = len(indices) // 3
        issues: list[str] = []

        if nf == 0:
            return {"watertight": False, "euler": 0, "issues": ["mesh has no faces"]}

        em = _build_edge_map(indices)
        n_edges = len(em)

        boundary = sum(1 for fs in em.values() if len(fs) == 1)
        non_manifold = sum(1 for fs in em.values() if len(fs) > 2)

        if boundary:
            issues.append(f"{boundary} boundary edge(s) — open mesh")
        if non_manifold:
            issues.append(f"{non_manifold} non-manifold edge(s) — shared by >2 faces")

        euler = _euler_characteristic(len(verts), n_edges, nf)
        if euler != 2 and not issues:
            issues.append(f"Euler characteristic is {euler}, expected 2 for a closed genus-0 surface")
        elif euler != 2:
            issues.append(f"Euler characteristic V−E+F = {euler} (expected 2)")

        return {
            "watertight": len(issues) == 0,
            "euler": euler,
            "issues": issues,
        }
    except Exception as exc:
        return {"watertight": False, "euler": 0, "issues": [str(exc)]}


# ─── STEP AP242 header parser ─────────────────────────────────────────────────

def step_ap242_metadata(step_text: str) -> dict:
    """
    Parse STEP AP242 PMI/semantic metadata from the text of a STEP file.
    Text-only parsing — no OCC dependency.

    Returns:
      {
        "schema": str,           # e.g. "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING"
        "product": str | None,   # first PRODUCT( name
        "description": str | None,
        "has_gdt": bool,         # true if GEOMETRIC_TOLERANCE or DATUM_FEATURE found
        "has_pmi": bool,         # true if PMI_REPRESENTATION_ITEM found
        "assembly_components": int,   # count of NEXT_ASSEMBLY_USAGE_OCCURRENCE
        "timestamp": str | None,
      }
    """
    try:
        result: dict[str, Any] = {
            "schema": None,
            "product": None,
            "description": None,
            "has_gdt": False,
            "has_pmi": False,
            "assembly_components": 0,
            "timestamp": None,
        }

        # Schema line: FILE_SCHEMA (('AP242_...'));
        m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", step_text, re.IGNORECASE)
        if m:
            result["schema"] = m.group(1)

        # FILE_NAME timestamp: FILE_NAME('...','2024-01-01T...', ...)
        m2 = re.search(r"FILE_NAME\s*\([^,]*,\s*'([^']+)'", step_text, re.IGNORECASE)
        if m2:
            result["timestamp"] = m2.group(1)

        # PRODUCT( 'name', 'description', ...
        m3 = re.search(r"PRODUCT\s*\(\s*'([^']*)'(?:\s*,\s*'([^']*)')?", step_text, re.IGNORECASE)
        if m3:
            result["product"] = m3.group(1)
            if m3.group(2):
                result["description"] = m3.group(2)

        # GD&T presence: GEOMETRIC_TOLERANCE or DATUM_FEATURE or DATUM_TARGET
        if re.search(r"GEOMETRIC_TOLERANCE|DATUM_FEATURE|DATUM_TARGET|TOLERANCE_VALUE", step_text, re.IGNORECASE):
            result["has_gdt"] = True

        # PMI: PMI_REPRESENTATION_ITEM or DRAUGHTING_MODEL_ITEM_ASSOCIATION
        if re.search(r"PMI_REPRESENTATION_ITEM|DRAUGHTING_MODEL_ITEM_ASSOCIATION|ANNOTATION_OCCURRENCE", step_text, re.IGNORECASE):
            result["has_pmi"] = True

        # Assembly tree: count NEXT_ASSEMBLY_USAGE_OCCURRENCE instances
        result["assembly_components"] = len(re.findall(r"NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(", step_text, re.IGNORECASE))

        return result
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ─── Interop readiness report ─────────────────────────────────────────────────

def interop_report(model: dict) -> dict:
    """
    Produce a downstream-interop readiness summary.

    Returns:
      {
        "ready": bool,
        "watertight": bool,
        "manifold": bool,
        "face_count": int,
        "vertex_count": int,
        "n_issues": int,
        "issues": [str, ...],
      }
    """
    try:
        verts = model.get("vertices", [])
        indices = model.get("indices", [])
        nf = len(indices) // 3

        wt = validate_watertight(model)
        nm = _detect_non_manifold(model)

        issues: list[str] = list(wt.get("issues", []))
        if nm["edges"]:
            issues.append(f"{len(nm['edges'])} non-manifold edge(s)")
        if nm["vertices"]:
            issues.append(f"{len(nm['vertices'])} non-manifold vertex/vertices")

        manifold = len(nm["edges"]) == 0

        return {
            "ready": wt["watertight"] and manifold,
            "watertight": wt["watertight"],
            "manifold": manifold,
            "face_count": nf,
            "vertex_count": len(verts),
            "n_issues": len(issues),
            "issues": issues,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _read_mesh(ctx: ProjectCtx, file_id: uuid.UUID):
    row = ctx.pool.fetchone(
        "select content, kind from files where id = $1 and project_id = $2 and deleted_at is null",
        file_id, ctx.project_id,
    )
    if not row:
        return None, "file not found"
    content, kind = row
    if kind != "mesh":
        return None, f"file is kind={kind}, expected mesh"
    try:
        return json.loads(content), None
    except Exception as e:
        return None, f"parse error: {e}"


def _write_mesh(ctx: ProjectCtx, file_id: uuid.UUID, doc: dict) -> Optional[str]:
    body = json.dumps(doc)
    try:
        ctx.pool.execute(
            "update files set content = $1, updated_at = now() where id = $2 and project_id = $3",
            body, file_id, ctx.project_id,
        )
        return None
    except Exception as e:
        return str(e)


def _parse_file_id(a: dict) -> tuple[Optional[uuid.UUID], Optional[str]]:
    raw = a.get("file_id", "").strip()
    if not raw:
        return None, "file_id is required"
    try:
        return uuid.UUID(raw), None
    except Exception:
        return None, "file_id must be a valid UUID"


# ─── Tool specs ───────────────────────────────────────────────────────────────

heal_mesh_spec = ToolSpec(
    name="heal_mesh",
    description=(
        "Run the full geometry healing pipeline on a .mesh file: "
        "stitch gaps, remove slivers, merge tiny edges, unify normals, "
        "remove duplicates, detect self-intersections, detect non-manifold "
        "geometry, and fill small holes. Returns a per-step delta report."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "UUID of the .mesh file."},
            "tolerance": {
                "type": "number",
                "description": "Merge/stitch tolerance in model units (default 1e-4).",
            },
        },
        "required": ["file_id"],
    },
)

validate_watertight_spec = ToolSpec(
    name="validate_watertight",
    description=(
        "Check whether a .mesh file is a closed watertight 2-manifold. "
        "Runs an Euler-characteristic check (V−E+F) and boundary-edge scan."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "UUID of the .mesh file."},
        },
        "required": ["file_id"],
    },
)

step_ap242_metadata_spec = ToolSpec(
    name="step_ap242_metadata",
    description=(
        "Parse STEP AP242 PMI and semantic metadata from a raw STEP file stored "
        "as a text/plain file. Extracts product name, GD&T annotation presence, "
        "assembly tree depth, and header timestamps."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "UUID of the STEP file (kind=step or text)."},
        },
        "required": ["file_id"],
    },
)

interop_report_spec = ToolSpec(
    name="interop_report",
    description=(
        "Generate a downstream interoperability readiness report for a .mesh file: "
        "watertight, manifold, issue count, and face/vertex stats."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "UUID of the .mesh file."},
        },
        "required": ["file_id"],
    },
)


# ─── Handlers ────────────────────────────────────────────────────────────────

@register(heal_mesh_spec, write=True)
async def run_heal_mesh(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    fid, err = _parse_file_id(a)
    if err:
        return err_payload(err, "BAD_ARGS")
    tol = float(a.get("tolerance", 1e-4))
    if tol <= 0:
        return err_payload("tolerance must be positive", "BAD_ARGS")
    mesh, err = _read_mesh(ctx, fid)
    if err:
        return err_payload(err, "NOT_FOUND")
    result = heal(mesh, tol)
    if not result.get("model"):
        return err_payload(result.get("reason", "heal failed"), "ERROR")
    write_err = _write_mesh(ctx, fid, result["model"])
    if write_err:
        return err_payload(write_err, "WRITE_ERR")
    return ok_payload({"file_id": str(fid), **result["report"]})


@register(validate_watertight_spec, write=False)
async def run_validate_watertight(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    fid, err = _parse_file_id(a)
    if err:
        return err_payload(err, "BAD_ARGS")
    mesh, err = _read_mesh(ctx, fid)
    if err:
        return err_payload(err, "NOT_FOUND")
    return ok_payload(validate_watertight(mesh))


@register(step_ap242_metadata_spec, write=False)
async def run_step_ap242_metadata(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    fid, err = _parse_file_id(a)
    if err:
        return err_payload(err, "BAD_ARGS")
    row = ctx.pool.fetchone(
        "select content from files where id = $1 and project_id = $2 and deleted_at is null",
        fid, ctx.project_id,
    )
    if not row:
        return err_payload("file not found", "NOT_FOUND")
    content = row[0] if isinstance(row, (list, tuple)) else row
    if not isinstance(content, str):
        try:
            content = content.decode("utf-8", errors="replace")
        except Exception:
            content = str(content)
    return ok_payload(step_ap242_metadata(content))


@register(interop_report_spec, write=False)
async def run_interop_report(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")
    fid, err = _parse_file_id(a)
    if err:
        return err_payload(err, "BAD_ARGS")
    mesh, err = _read_mesh(ctx, fid)
    if err:
        return err_payload(err, "NOT_FOUND")
    return ok_payload(interop_report(mesh))
