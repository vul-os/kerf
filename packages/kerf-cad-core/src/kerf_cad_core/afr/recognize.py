"""
kerf_cad_core.afr.recognize
============================
Automatic Feature Recognition (AFR) — re-parameterize an imported "dumb"
B-rep into an ordered, editable feature tree.

Algorithm
---------
Attribute-Adjacency-Graph (AAG):
  * Faces are graph nodes annotated with surface type and curvature.
  * Edges carry a convexity label (convex / concave / tangent).
  * Subgraph queries identify classical machining/design features.

Supported features
------------------
  through_hole     — cylindrical face pair sharing an axis, no floor face
  blind_hole       — single cylindrical face + floor (planar bottom cap)
  counterbore      — two coaxial cylinders of different radii + step face
  countersink      — conical face + cylindrical stub, coaxial
  pocket           — concave closed face loop with a planar floor
  slot             — rectangular pocket whose length >> width (aspect ≥ 3)
  boss             — convex cylindrical protrusion above a base face
  fillet           — constant-radius blend face between two planar faces
  chamfer          — planar bevel at 45° ± tolerance between two faces
  rib              — thin planar protrusion connected at base edges
  step             — two coplanar faces separated by a single riser face

Input topology dict
-------------------
{
  "faces": [
    {
      "id":          str | int,
      "type":        "planar" | "cylindrical" | "conical" | "spherical" | "toroidal" | "other",
      "normal":      [nx, ny, nz],      # for planar faces; axis for cylindrical/conical
      "radius":      float,             # cylindrical / fillet radius (0 if not curved)
      "area":        float,             # optional, used for rib/boss heuristics
      "convexity":   "convex" | "concave" | "flat",  # face convexity relative to solid
      "adjacent":    [face_id, ...]     # list of adjacent face ids (shared edges)
    },
    ...
  ],
  "edges": [                            # optional; used for convexity labels
    {
      "id":          str | int,
      "face_a":      str | int,
      "face_b":      str | int,
      "convexity":   "convex" | "concave" | "tangent",
      "length":      float
    },
    ...
  ]
}

OR a triangle-mesh dict with face clustering:
{
  "vertices":  [[x,y,z], ...],
  "triangles": [[i,j,k], ...],
  "face_clusters": [
    {
      "id":        int,
      "type":      "planar" | "cylindrical" | ...,
      "normal":    [nx, ny, nz],
      "radius":    float,
      "area":      float,
      "convexity": "convex" | "concave" | "flat",
      "adjacent":  [cluster_id, ...]
    },
    ...
  ]
}

Output
------
{
  "ok":      bool,
  "features": [
    {
      "type":       str,               # feature type name
      "params":     dict,              # dia, depth, radius, position, axis, width, …
      "face_ids":   list,              # face IDs participating in this feature
      "confidence": float,             # 0.0–1.0
    },
    ...
  ],
  "feature_tree": [                    # ordered: base solid first, then subtractive/additive
    { "type": str, "index": int }      # index into features list
  ],
  "reason": str                        # human-readable note or error message
}

Never raises; always returns the dict above.

References
----------
Joshi & Chang (1988) "Graph-based heuristics for recognition of machined
features from a 3D solid model", CAD 20(2), 58-66.

Marefat & Kashyap (1990) "Geometric reasoning for recognition of 3D object
features", IEEE PAMI 12(10), 949–965.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

FaceDict = Dict[str, Any]
EdgeDict = Dict[str, Any]
FeatureDict = Dict[str, Any]
TopologyDict = Dict[str, Any]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AXIS_PARALLEL_TOL = 0.05   # max dot-product deviation for parallel axes
_AXIS_SAME_TOL = 0.10       # max distance between axis origins for "same axis"
_RADIUS_REL_TOL = 0.05      # relative tolerance for radius comparison
_ANGLE_TOL_DEG = 5.0        # tolerance for angle checks (degrees)
_SLOT_ASPECT_RATIO = 3.0    # length/width ratio threshold for slot vs pocket
_CHAMFER_ANGLE_DEG = 45.0   # nominal chamfer angle

# Feature ordering weights (lower = earlier in tree = "more base")
_ORDER_WEIGHTS = {
    "base":         0,
    "step":         10,
    "boss":         20,
    "rib":          25,
    "pocket":       30,
    "slot":         35,
    "through_hole": 40,
    "blind_hole":   45,
    "counterbore":  50,
    "countersink":  55,
    "fillet":       60,
    "chamfer":      65,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _unit(v: Sequence[float]) -> List[float]:
    """Return unit vector or [0,0,1] for zero-length input."""
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    mag = math.sqrt(x * x + y * y + z * z)
    if mag < 1e-12:
        return [0.0, 0.0, 1.0]
    return [x / mag, y / mag, z / mag]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _axes_parallel(a1: Sequence[float], a2: Sequence[float]) -> bool:
    """Return True if unit vectors a1 and a2 are parallel (or anti-parallel)."""
    d = abs(_dot(_unit(a1), _unit(a2)))
    return d >= (1.0 - _AXIS_PARALLEL_TOL)


def _radii_match(r1: float, r2: float) -> bool:
    mid = (abs(r1) + abs(r2)) / 2.0
    if mid < 1e-9:
        return True
    return abs(r1 - r2) / mid <= _RADIUS_REL_TOL


def _get_faces(topology: TopologyDict) -> List[FaceDict]:
    """Extract normalised face list from topology or mesh-cluster dict."""
    if "faces" in topology:
        return list(topology["faces"])
    if "face_clusters" in topology:
        return list(topology["face_clusters"])
    return []


def _get_edges(topology: TopologyDict) -> List[EdgeDict]:
    return list(topology.get("edges", []))


def _face_by_id(faces: List[FaceDict], fid: Any) -> Optional[FaceDict]:
    for f in faces:
        if f.get("id") == fid:
            return f
    return None


def _adjacency_map(faces: List[FaceDict]) -> Dict[Any, List[Any]]:
    """Build {face_id: [adjacent_face_id, ...]} from each face's 'adjacent' list."""
    adj: Dict[Any, List[Any]] = {}
    for f in faces:
        fid = f.get("id")
        neighbors = list(f.get("adjacent", []))
        adj[fid] = neighbors
    return adj


def _edge_convexity(
    edges: List[EdgeDict], fa_id: Any, fb_id: Any
) -> Optional[str]:
    """Return convexity of the shared edge between fa_id and fb_id, or None."""
    for e in edges:
        if (e.get("face_a") == fa_id and e.get("face_b") == fb_id) or \
           (e.get("face_a") == fb_id and e.get("face_b") == fa_id):
            return e.get("convexity")
    return None


def _cylindrical_faces(faces: List[FaceDict]) -> List[FaceDict]:
    return [f for f in faces if f.get("type") == "cylindrical"]


def _planar_faces(faces: List[FaceDict]) -> List[FaceDict]:
    return [f for f in faces if f.get("type") == "planar"]


def _conical_faces(faces: List[FaceDict]) -> List[FaceDict]:
    return [f for f in faces if f.get("type") == "conical"]


def _toroidal_faces(faces: List[FaceDict]) -> List[FaceDict]:
    return [f for f in faces if f.get("type") == "toroidal"]


# ---------------------------------------------------------------------------
# Feature detectors
# ---------------------------------------------------------------------------

def _detect_holes(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect through-holes and blind-holes from cylindrical faces."""
    features: List[FeatureDict] = []
    cyls = _cylindrical_faces(faces)

    for cyl in cyls:
        fid = cyl.get("id")
        if fid in used:
            continue

        axis = cyl.get("normal", [0.0, 0.0, 1.0])
        radius = float(cyl.get("radius", 0.0))
        convexity = cyl.get("convexity", "concave")

        # Only consider concave cylinders (holes into a body, not bosses).
        if convexity == "convex":
            continue

        # Find adjacent planar caps (floor faces).
        neighbor_ids = adj.get(fid, [])
        cap_faces = []
        for nid in neighbor_ids:
            nf = _face_by_id(faces, nid)
            if nf is None:
                continue
            if nf.get("type") == "planar":
                n_normal = nf.get("normal", [0.0, 0.0, 1.0])
                # Cap normal should be parallel to cylinder axis.
                if _axes_parallel(axis, n_normal):
                    cap_faces.append(nf)

        # Estimate depth from area / (2*pi*r) if no explicit depth given.
        area = float(cyl.get("area", 0.0))
        if radius > 1e-6:
            depth = area / (2.0 * math.pi * radius)
        else:
            depth = 0.0

        # Position heuristic: centroid of cyl or average of caps.
        position = list(cyl.get("centroid", [0.0, 0.0, 0.0]))

        if len(cap_faces) == 0:
            # No floor → through-hole.
            feat: FeatureDict = {
                "type": "through_hole",
                "params": {
                    "diameter": round(radius * 2.0, 6),
                    "axis": [round(v, 6) for v in _unit(axis)],
                    "depth": round(depth, 6),
                    "position": position,
                },
                "face_ids": [fid],
                "confidence": 0.85,
            }
            features.append(feat)
            used.add(fid)

        elif len(cap_faces) == 1:
            # One floor cap → blind-hole.
            used.add(fid)
            used.add(cap_faces[0].get("id"))
            feat = {
                "type": "blind_hole",
                "params": {
                    "diameter": round(radius * 2.0, 6),
                    "axis": [round(v, 6) for v in _unit(axis)],
                    "depth": round(depth, 6),
                    "position": position,
                },
                "face_ids": [fid, cap_faces[0].get("id")],
                "confidence": 0.87,
            }
            features.append(feat)

        else:
            # Two caps → also through (caps are entry/exit rings or flanges).
            used.add(fid)
            for cf in cap_faces:
                used.add(cf.get("id"))
            feat = {
                "type": "through_hole",
                "params": {
                    "diameter": round(radius * 2.0, 6),
                    "axis": [round(v, 6) for v in _unit(axis)],
                    "depth": round(depth, 6),
                    "position": position,
                },
                "face_ids": [fid] + [cf.get("id") for cf in cap_faces],
                "confidence": 0.90,
            }
            features.append(feat)

    return features


def _detect_counterbore(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect counterbore: two coaxial concave cylinders of different radii + step."""
    features: List[FeatureDict] = []
    cyls = [f for f in _cylindrical_faces(faces) if f.get("convexity") != "convex"]

    for i, c1 in enumerate(cyls):
        fid1 = c1.get("id")
        if fid1 in used:
            continue
        axis1 = c1.get("normal", [0.0, 0.0, 1.0])
        r1 = float(c1.get("radius", 0.0))

        for c2 in cyls[i + 1:]:
            fid2 = c2.get("id")
            if fid2 in used:
                continue
            axis2 = c2.get("normal", [0.0, 0.0, 1.0])
            r2 = float(c2.get("radius", 0.0))

            # Must be coaxial and different radii.
            if not _axes_parallel(axis1, axis2):
                continue
            if _radii_match(r1, r2):
                continue  # same radius → not a counterbore

            # Look for a shared planar step face adjacent to both cylinders.
            n1 = set(adj.get(fid1, []))
            n2 = set(adj.get(fid2, []))
            shared_neighbors = n1 & n2
            step_face_ids = []
            for sid in shared_neighbors:
                sf = _face_by_id(faces, sid)
                if sf is not None and sf.get("type") == "planar":
                    step_face_ids.append(sid)

            if not step_face_ids:
                continue

            r_bore = max(r1, r2)     # larger = counterbore
            r_drill = min(r1, r2)    # smaller = drill
            area1 = float(c1.get("area", 0.0))
            area2 = float(c2.get("area", 0.0))
            depth_bore = area1 / (2.0 * math.pi * r1) if r1 > 1e-6 else 0.0
            depth_drill = area2 / (2.0 * math.pi * r2) if r2 > 1e-6 else 0.0

            used.add(fid1)
            used.add(fid2)
            for sid in step_face_ids:
                used.add(sid)

            position = list(c1.get("centroid", [0.0, 0.0, 0.0]))
            feat: FeatureDict = {
                "type": "counterbore",
                "params": {
                    "bore_diameter": round(r_bore * 2.0, 6),
                    "drill_diameter": round(r_drill * 2.0, 6),
                    "bore_depth": round(depth_bore, 6),
                    "drill_depth": round(depth_drill, 6),
                    "axis": [round(v, 6) for v in _unit(axis1)],
                    "position": position,
                },
                "face_ids": [fid1, fid2] + list(step_face_ids),
                "confidence": 0.82,
            }
            features.append(feat)
            break  # c1 is consumed

    return features


def _detect_countersink(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect countersink: conical face + optional inner cylinder, coaxial."""
    features: List[FeatureDict] = []
    conics = _conical_faces(faces)

    for con in conics:
        fid_con = con.get("id")
        if fid_con in used:
            continue
        axis_con = con.get("normal", [0.0, 0.0, 1.0])
        half_angle = float(con.get("half_angle", 45.0))  # degrees

        # Look for an adjacent cylindrical face sharing the same axis.
        inner_cyl = None
        for nid in adj.get(fid_con, []):
            nf = _face_by_id(faces, nid)
            if nf is None or nf.get("id") in used:
                continue
            if nf.get("type") == "cylindrical" and _axes_parallel(axis_con, nf.get("normal", [0, 0, 1])):
                inner_cyl = nf
                break

        face_ids = [fid_con]
        r_top = float(con.get("radius", 0.0))
        position = list(con.get("centroid", [0.0, 0.0, 0.0]))
        if inner_cyl is not None:
            face_ids.append(inner_cyl.get("id"))
            used.add(inner_cyl.get("id"))

        used.add(fid_con)
        feat: FeatureDict = {
            "type": "countersink",
            "params": {
                "top_diameter": round(r_top * 2.0, 6),
                "half_angle_deg": round(half_angle, 3),
                "axis": [round(v, 6) for v in _unit(axis_con)],
                "position": position,
            },
            "face_ids": face_ids,
            "confidence": 0.80,
        }
        features.append(feat)

    return features


def _detect_pockets_and_slots(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect pockets and slots: concave closed face loop with a planar floor."""
    features: List[FeatureDict] = []
    planar = _planar_faces(faces)

    for floor in planar:
        fid_floor = floor.get("id")
        if fid_floor in used:
            continue

        # A pocket floor must not be a convex face (convex = protrusion, not recess).
        if floor.get("convexity") == "convex":
            continue

        floor_normal = floor.get("normal", [0.0, 0.0, 1.0])
        floor_area = float(floor.get("area", 0.0))

        # Gather wall faces: concave planars or cylinders adjacent to floor.
        wall_ids = []
        all_concave = True
        for nid in adj.get(fid_floor, []):
            nf = _face_by_id(faces, nid)
            if nf is None or nf.get("id") in used:
                continue
            # Wall normal roughly perpendicular to floor normal.
            wall_normal = nf.get("normal", [0.0, 0.0, 1.0])
            perp = abs(_dot(_unit(floor_normal), _unit(wall_normal)))
            if perp > 0.3:
                continue  # not a wall face
            # Concavity check.
            conv = nf.get("convexity", "concave")
            edge_conv = _edge_convexity(edges, fid_floor, nid)
            is_concave = conv == "concave" or edge_conv == "concave"
            if not is_concave:
                all_concave = False
            wall_ids.append(nid)

        if len(wall_ids) < 2:
            continue
        if not all_concave:
            continue

        # Estimate pocket depth from wall face areas.
        wall_area_total = 0.0
        for wid in wall_ids:
            wf = _face_by_id(faces, wid)
            if wf is not None:
                wall_area_total += float(wf.get("area", 0.0))

        # Simple depth heuristic: total_wall_area / perimeter_estimate.
        perimeter = 4.0 * math.sqrt(max(floor_area, 1e-9))  # rough
        depth = wall_area_total / max(perimeter, 1e-6)

        # Classify slot vs pocket by aspect ratio.
        # Use bounding extents if available, otherwise fall back to area heuristic.
        bbox = floor.get("bbox")  # [xmin,ymin,xmax,ymax] in floor plane
        ftype = "pocket"
        width = math.sqrt(floor_area) if floor_area > 0 else 1.0
        length = width
        if bbox and len(bbox) >= 4:
            w = abs(float(bbox[2]) - float(bbox[0]))
            l = abs(float(bbox[3]) - float(bbox[1]))
            width, length = min(w, l), max(w, l)
            if width > 1e-6 and (length / width) >= _SLOT_ASPECT_RATIO:
                ftype = "slot"

        all_ids = [fid_floor] + wall_ids
        used.add(fid_floor)
        for wid in wall_ids:
            used.add(wid)

        position = list(floor.get("centroid", [0.0, 0.0, 0.0]))
        if ftype == "slot":
            feat: FeatureDict = {
                "type": "slot",
                "params": {
                    "width": round(width, 6),
                    "length": round(length, 6),
                    "depth": round(depth, 6),
                    "floor_normal": [round(v, 6) for v in _unit(floor_normal)],
                    "position": position,
                },
                "face_ids": all_ids,
                "confidence": 0.75,
            }
        else:
            feat = {
                "type": "pocket",
                "params": {
                    "floor_area": round(floor_area, 6),
                    "depth": round(depth, 6),
                    "wall_count": len(wall_ids),
                    "floor_normal": [round(v, 6) for v in _unit(floor_normal)],
                    "position": position,
                },
                "face_ids": all_ids,
                "confidence": 0.78,
            }
        features.append(feat)

    return features


def _detect_bosses(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect bosses: convex cylindrical protrusions above a base face."""
    features: List[FeatureDict] = []
    cyls = [f for f in _cylindrical_faces(faces) if f.get("convexity") == "convex"]

    for cyl in cyls:
        fid = cyl.get("id")
        if fid in used:
            continue

        axis = cyl.get("normal", [0.0, 0.0, 1.0])
        radius = float(cyl.get("radius", 0.0))
        area = float(cyl.get("area", 0.0))
        depth = area / (2.0 * math.pi * radius) if radius > 1e-6 else 0.0

        # Look for a planar top cap.
        top_cap = None
        for nid in adj.get(fid, []):
            nf = _face_by_id(faces, nid)
            if nf and nf.get("type") == "planar" and _axes_parallel(axis, nf.get("normal", [0, 0, 1])):
                top_cap = nf
                break

        # Look for a planar base face.
        base_face = None
        for nid in adj.get(fid, []):
            nf = _face_by_id(faces, nid)
            if nf and nf.get("type") == "planar" and nf.get("id") != (top_cap.get("id") if top_cap else None):
                # Normal should be anti-parallel to axis (base).
                n_normal = nf.get("normal", [0, 0, 1])
                perp = abs(_dot(_unit(axis), _unit(n_normal)))
                if perp < 0.5:
                    base_face = nf
                    break

        face_ids = [fid]
        if top_cap:
            face_ids.append(top_cap.get("id"))
        if base_face:
            face_ids.append(base_face.get("id"))

        used.add(fid)
        if top_cap:
            used.add(top_cap.get("id"))

        position = list(cyl.get("centroid", [0.0, 0.0, 0.0]))
        feat: FeatureDict = {
            "type": "boss",
            "params": {
                "diameter": round(radius * 2.0, 6),
                "height": round(depth, 6),
                "axis": [round(v, 6) for v in _unit(axis)],
                "position": position,
            },
            "face_ids": face_ids,
            "confidence": 0.80,
        }
        features.append(feat)

    return features


def _detect_fillets(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect fillets: toroidal or constant-radius cylindrical blend faces."""
    features: List[FeatureDict] = []

    # Toroidal faces are always fillets/rounds.
    for f in _toroidal_faces(faces):
        fid = f.get("id")
        if fid in used:
            continue
        radius = float(f.get("radius", 0.0))
        used.add(fid)
        position = list(f.get("centroid", [0.0, 0.0, 0.0]))
        features.append({
            "type": "fillet",
            "params": {
                "radius": round(radius, 6),
                "position": position,
            },
            "face_ids": [fid],
            "confidence": 0.90,
        })

    # Small-radius cylindrical faces tangent to two planars are also fillets.
    for cyl in _cylindrical_faces(faces):
        fid = cyl.get("id")
        if fid in used:
            continue
        radius = float(cyl.get("radius", 0.0))
        if radius < 1e-6:
            continue

        # Must be tangent (not concave/convex sharp) to neighbors.
        neighbor_ids = adj.get(fid, [])
        planar_tangent_count = 0
        for nid in neighbor_ids:
            ec = _edge_convexity(edges, fid, nid)
            nf = _face_by_id(faces, nid)
            if nf and nf.get("type") == "planar" and ec == "tangent":
                planar_tangent_count += 1

        if planar_tangent_count >= 2:
            area = float(cyl.get("area", 0.0))
            # Small cross-section relative to radius suggests a fillet vs a cylinder.
            # arc_length ≈ area / (cyl_length), cyl_length from depth heuristic.
            # We simply check: area < 4 * pi * r^2 (less than a full sphere worth).
            if area < 4.0 * math.pi * radius * radius:
                used.add(fid)
                position = list(cyl.get("centroid", [0.0, 0.0, 0.0]))
                features.append({
                    "type": "fillet",
                    "params": {
                        "radius": round(radius, 6),
                        "position": position,
                    },
                    "face_ids": [fid],
                    "confidence": 0.82,
                })

    return features


def _detect_chamfers(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect chamfers: planar bevel faces at ~45° between two other faces."""
    features: List[FeatureDict] = []
    planar = [f for f in _planar_faces(faces) if f.get("id") not in used]

    for f in planar:
        fid = f.get("id")
        if fid in used:
            continue
        normal = _unit(f.get("normal", [0.0, 0.0, 1.0]))
        area = float(f.get("area", 0.0))

        # A chamfer face has its normal at ~45° to at least two adjacent faces.
        neighbor_ids = adj.get(fid, [])
        chamfer_neighbors = []
        for nid in neighbor_ids:
            nf = _face_by_id(faces, nid)
            if nf is None:
                continue
            n2 = _unit(nf.get("normal", [0.0, 0.0, 1.0]))
            ang_deg = math.degrees(math.acos(max(-1.0, min(1.0, abs(_dot(normal, n2))))))
            # Chamfer: face normal at 30–60° to adjacent face normals.
            if 30.0 <= ang_deg <= 60.0:
                chamfer_neighbors.append(nid)

        if len(chamfer_neighbors) >= 2:
            used.add(fid)
            position = list(f.get("centroid", [0.0, 0.0, 0.0]))
            features.append({
                "type": "chamfer",
                "params": {
                    "normal": [round(v, 6) for v in normal],
                    "area": round(area, 6),
                    "position": position,
                },
                "face_ids": [fid],
                "confidence": 0.72,
            })

    return features


def _detect_ribs(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect ribs: thin convex planar protrusion connected at base edges."""
    features: List[FeatureDict] = []
    planar = [f for f in _planar_faces(faces) if f.get("id") not in used]

    for f in planar:
        fid = f.get("id")
        if fid in used:
            continue
        area = float(f.get("area", 0.0))
        convexity = f.get("convexity", "flat")

        # A rib side face is typically convex and has a very low aspect ratio
        # (thin strip). We heuristically check if the face has a small area and
        # ≥ 2 concave-edge neighbors (the rib base edges).
        if convexity != "convex":
            continue

        concave_edge_count = 0
        for nid in adj.get(fid, []):
            ec = _edge_convexity(edges, fid, nid)
            if ec == "concave":
                concave_edge_count += 1

        if concave_edge_count >= 2:
            used.add(fid)
            normal = _unit(f.get("normal", [0.0, 0.0, 1.0]))
            position = list(f.get("centroid", [0.0, 0.0, 0.0]))
            features.append({
                "type": "rib",
                "params": {
                    "area": round(area, 6),
                    "normal": [round(v, 6) for v in normal],
                    "position": position,
                },
                "face_ids": [fid],
                "confidence": 0.65,
            })

    return features


def _detect_steps(
    faces: List[FaceDict],
    edges: List[EdgeDict],
    adj: Dict[Any, List[Any]],
    used: set,
) -> List[FeatureDict]:
    """Detect steps: two coplanar faces separated by a single riser face."""
    features: List[FeatureDict] = []
    planar = [f for f in _planar_faces(faces) if f.get("id") not in used]

    for f in planar:
        fid = f.get("id")
        if fid in used:
            continue
        normal = _unit(f.get("normal", [0.0, 0.0, 1.0]))

        # Find a riser (perpendicular adjacent planar).
        for nid in adj.get(fid, []):
            nf = _face_by_id(faces, nid)
            if nf is None or nf.get("id") in used or nf.get("type") != "planar":
                continue
            n2 = _unit(nf.get("normal", [0.0, 0.0, 1.0]))
            # Riser: normal perpendicular to f's normal.
            if abs(_dot(normal, n2)) > 0.3:
                continue

            # Find a second coplanar face adjacent to the riser (but not fid).
            for nid2 in adj.get(nid, []):
                if nid2 == fid:
                    continue
                nf2 = _face_by_id(faces, nid2)
                if nf2 is None or nf2.get("id") in used or nf2.get("type") != "planar":
                    continue
                n3 = _unit(nf2.get("normal", [0.0, 0.0, 1.0]))
                # Coplanar with f (same normal direction).
                if abs(_dot(normal, n3)) > 0.95:
                    used.add(fid)
                    used.add(nf.get("id"))
                    used.add(nf2.get("id"))
                    position = list(f.get("centroid", [0.0, 0.0, 0.0]))
                    features.append({
                        "type": "step",
                        "params": {
                            "normal": [round(v, 6) for v in normal],
                            "position": position,
                        },
                        "face_ids": [fid, nf.get("id"), nf2.get("id")],
                        "confidence": 0.70,
                    })
                    break
            else:
                continue
            break

    return features


# ---------------------------------------------------------------------------
# Feature tree ordering
# ---------------------------------------------------------------------------

def _build_feature_tree(features: List[FeatureDict]) -> List[Dict[str, Any]]:
    """Order features: base solid first, then additive (boss/rib), then subtractive."""
    indexed = list(enumerate(features))
    indexed.sort(key=lambda iv: _ORDER_WEIGHTS.get(iv[1].get("type", ""), 50))
    return [{"type": item["type"], "index": i} for i, item in indexed]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recognize_features(topology: Any) -> Dict[str, Any]:
    """Recognize machining/design features from a B-rep topology or mesh dict.

    Parameters
    ----------
    topology : dict
        B-rep topology (faces + optional edges) or mesh-cluster dict.
        See module docstring for full schema.

    Returns
    -------
    dict with keys: ok, features, feature_tree, reason.
    Never raises.
    """
    _EMPTY = {"ok": False, "features": [], "feature_tree": [], "reason": ""}

    try:
        if not isinstance(topology, dict):
            return {**_EMPTY, "reason": "topology must be a dict"}

        faces = _get_faces(topology)
        if not faces:
            return {"ok": True, "features": [], "feature_tree": [], "reason": "no faces in topology"}

        edges = _get_edges(topology)
        adj = _adjacency_map(faces)

        # Canonicalise face IDs to ensure they are present.
        for i, f in enumerate(faces):
            if "id" not in f or f["id"] is None:
                f["id"] = i

        used: set = set()
        features: List[FeatureDict] = []

        # Run detectors in priority order (most specific first).
        features += _detect_counterbore(faces, edges, adj, used)
        features += _detect_countersink(faces, edges, adj, used)
        features += _detect_holes(faces, edges, adj, used)
        features += _detect_bosses(faces, edges, adj, used)
        features += _detect_pockets_and_slots(faces, edges, adj, used)
        features += _detect_ribs(faces, edges, adj, used)
        features += _detect_fillets(faces, edges, adj, used)
        features += _detect_chamfers(faces, edges, adj, used)
        features += _detect_steps(faces, edges, adj, used)

        feature_tree = _build_feature_tree(features)

        return {
            "ok": True,
            "features": features,
            "feature_tree": feature_tree,
            "reason": f"recognized {len(features)} feature(s) from {len(faces)} face(s)",
        }

    except Exception as exc:  # pragma: no cover — defensive outer catch
        return {
            "ok": False,
            "features": [],
            "feature_tree": [],
            "reason": f"afr error: {exc}",
        }


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

if _REGISTRY_AVAILABLE:

    _afr_spec = ToolSpec(
        name="afr_recognize_features",
        description=(
            "Automatic Feature Recognition: analyse a B-rep topology or mesh-cluster "
            "dict and return an ordered editable feature list. Recognises through-holes, "
            "blind holes, counterbores, countersinks, pockets, slots, bosses, fillets, "
            "chamfers, ribs, and steps. Returns {ok, features, feature_tree, reason}. "
            "Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topology": {
                    "type": "object",
                    "description": (
                        "B-rep topology dict with 'faces' list (each face has id, type, "
                        "normal, radius, area, convexity, adjacent) and optional 'edges' "
                        "list (each edge has id, face_a, face_b, convexity, length). "
                        "Alternatively a mesh dict with 'vertices', 'triangles', and "
                        "'face_clusters' may be provided."
                    ),
                },
            },
            "required": ["topology"],
        },
    )

    @register(_afr_spec)
    async def run_afr_recognize(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        topo = a.get("topology")
        if not isinstance(topo, dict):
            return err_payload("topology must be a dict", "BAD_ARGS")

        result = recognize_features(topo)
        return ok_payload(result)
