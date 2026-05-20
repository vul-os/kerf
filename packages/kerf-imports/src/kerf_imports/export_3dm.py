"""export_3dm.py — 3DM (OpenNURBS) exporter via rhino3dm.

Mirrors the structure of rhino3dm_route.py's /import-3dm handler in the
export direction: accepts a list of KerfObject dicts (Body/NURBS surface/curve
representations) and writes a Rhino .3dm binary.

Public API
----------
export_to_3dm(objects, *, version=7) -> bytes
    Convert a list of KerfObject dicts to a .3dm binary blob.

build_nurbs_curve_payload(degree, knots, control_points, weights=None) -> dict
    Pure-Python helper: construct the canonical ``rhino_json``-based wire-format
    dict for a NURBS curve (no rhino3dm import required).

build_nurbs_surface_payload(degree_u, degree_v, knots_u, knots_v,
                             control_points, weights=None) -> dict
    Same for a NURBS surface.

parse_nurbs_curve_payload(payload) -> dict
    Extract the serialisation-prep fields from a NURBS curve payload
    (pure-Python, no rhino3dm).

parse_nurbs_surface_payload(payload) -> dict
    Same for a NURBS surface.

KerfObject wire format
----------------------
A KerfObject is a plain dict with at minimum:

    {
        "kind":  "sketch" | "surf" | "feature" | "mesh" | "point",
        "content_json": {
            "source": "rhino3dm",
            "kind": ...,
            # One of:
            "rhino_json": {...},          # full rhino3dm Encode() round-trip
            # --- or for NURBS curves (kind="sketch") ---
            "nurbs_curve": {
                "degree": int,
                "knots":  [float, ...],
                "control_points": [[x, y, z], ...],
                "weights": [float, ...]   # optional; 1.0 if omitted
            },
            # --- or for NURBS surfaces (kind="surf") ---
            "nurbs_surface": {
                "degree_u": int,
                "degree_v": int,
                "knots_u":  [float, ...],
                "knots_v":  [float, ...],
                "control_points": [[[x, y, z], ...], ...],  # [u][v]
                "weights": [[float, ...], ...]               # optional
            },
        }
    }

If rhino3dm is unavailable the function raises ``ImportError``.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Sequence

__all__ = [
    "export_to_3dm",
    "build_nurbs_curve_payload",
    "build_nurbs_surface_payload",
    "parse_nurbs_curve_payload",
    "parse_nurbs_surface_payload",
]

# ---------------------------------------------------------------------------
# Pure-Python serialisation helpers (no rhino3dm dependency)
# ---------------------------------------------------------------------------


def build_nurbs_curve_payload(
    degree: int,
    knots: Sequence[float],
    control_points: Sequence[Sequence[float]],
    weights: Sequence[float] | None = None,
) -> dict:
    """Return the canonical wire-format dict for a NURBS curve.

    The returned dict is suitable as ``content_json`` for a KerfObject with
    ``kind="sketch"``.  It carries a ``nurbs_curve`` sub-dict so that
    :func:`export_to_3dm` can reconstruct the rhino3dm object without
    requiring the caller to pre-import rhino3dm.

    Parameters
    ----------
    degree:
        Polynomial degree (≥ 1).
    knots:
        Knot vector.  rhino3dm uses a (n + degree - 1)-length vector where
        n is the number of control points (the first and last knot are NOT
        doubled in the rhino3dm convention).
    control_points:
        Sequence of [x, y, z] (or [x, y, z, w] homogeneous) points.
    weights:
        Optional rational weights; must match len(control_points) if given.
    """
    n = len(control_points)
    if weights is None:
        weights = [1.0] * n
    if len(weights) != n:
        raise ValueError(
            f"weights length {len(weights)} must match control_points length {n}"
        )
    return {
        "source": "kerf",
        "kind": "sketch",
        "nurbs_curve": {
            "degree": int(degree),
            "knots": [float(k) for k in knots],
            "control_points": [[float(v) for v in pt[:3]] for pt in control_points],
            "weights": [float(w) for w in weights],
        },
    }


def build_nurbs_surface_payload(
    degree_u: int,
    degree_v: int,
    knots_u: Sequence[float],
    knots_v: Sequence[float],
    control_points: Sequence[Sequence[Sequence[float]]],
    weights: Sequence[Sequence[float]] | None = None,
) -> dict:
    """Return the canonical wire-format dict for a NURBS surface.

    Parameters
    ----------
    degree_u, degree_v:
        Polynomial degree in u and v directions.
    knots_u, knots_v:
        Knot vectors for u and v.
    control_points:
        2-D array [u][v] of [x, y, z] points.
    weights:
        Optional 2-D array [u][v] of weights.
    """
    n_u = len(control_points)
    n_v = len(control_points[0]) if n_u > 0 else 0

    if weights is None:
        weights = [[1.0] * n_v for _ in range(n_u)]

    return {
        "source": "kerf",
        "kind": "surf",
        "nurbs_surface": {
            "degree_u": int(degree_u),
            "degree_v": int(degree_v),
            "knots_u": [float(k) for k in knots_u],
            "knots_v": [float(k) for k in knots_v],
            "control_points": [
                [[float(v) for v in pt[:3]] for pt in row]
                for row in control_points
            ],
            "weights": [
                [float(w) for w in row]
                for row in weights
            ],
        },
    }


def parse_nurbs_curve_payload(payload: dict) -> dict:
    """Extract and validate NURBS curve fields from a content_json payload.

    Returns a dict with keys: degree, knots, control_points, weights.
    Raises ``KeyError`` / ``TypeError`` if required fields are absent or
    malformed.
    """
    nc = payload["nurbs_curve"]
    return {
        "degree": int(nc["degree"]),
        "knots": [float(k) for k in nc["knots"]],
        "control_points": [[float(v) for v in pt] for pt in nc["control_points"]],
        "weights": [float(w) for w in nc.get("weights", [1.0] * len(nc["control_points"]))],
    }


def parse_nurbs_surface_payload(payload: dict) -> dict:
    """Extract and validate NURBS surface fields from a content_json payload.

    Returns a dict with keys: degree_u, degree_v, knots_u, knots_v,
    control_points, weights.
    """
    ns = payload["nurbs_surface"]
    cps = ns["control_points"]
    n_u = len(cps)
    n_v = len(cps[0]) if n_u > 0 else 0
    raw_w = ns.get("weights")
    if raw_w is None:
        weights = [[1.0] * n_v for _ in range(n_u)]
    else:
        weights = [[float(w) for w in row] for row in raw_w]
    return {
        "degree_u": int(ns["degree_u"]),
        "degree_v": int(ns["degree_v"]),
        "knots_u": [float(k) for k in ns["knots_u"]],
        "knots_v": [float(k) for k in ns["knots_v"]],
        "control_points": [[
            [float(v) for v in pt] for pt in row
        ] for row in cps],
        "weights": weights,
    }


# ---------------------------------------------------------------------------
# Internal: rhino3dm object builders
# ---------------------------------------------------------------------------

def _add_nurbs_curve(model, nc_data: dict) -> bool:  # type: ignore[valid-type]
    """Build a rhino3dm.NurbsCurve and add it to model.Objects.

    Returns True on success, False on any error.
    """
    try:
        import rhino3dm  # noqa: PLC0415
    except ImportError:
        return False

    try:
        degree = int(nc_data["degree"])
        knots = nc_data["knots"]
        cps = nc_data["control_points"]
        weights = nc_data.get("weights") or [1.0] * len(cps)

        is_rational = any(abs(w - 1.0) > 1e-15 for w in weights)
        curve = rhino3dm.NurbsCurve(3, is_rational, degree, len(cps))

        for i, (pt, w) in enumerate(zip(cps, weights)):
            curve.Points[i] = rhino3dm.Point4d(
                float(pt[0]) * w,
                float(pt[1]) * w,
                float(pt[2]) * w,
                float(w),
            )

        # rhino3dm knot vector has length n + degree - 1
        for i, k in enumerate(knots):
            curve.Knots[i] = float(k)

        model.Objects.AddCurve(curve)
        return True
    except Exception:
        return False


def _add_nurbs_surface(model, ns_data: dict) -> bool:  # type: ignore[valid-type]
    """Build a rhino3dm.NurbsSurface and add it to model.Objects.

    Returns True on success, False on any error.
    """
    try:
        import rhino3dm  # noqa: PLC0415
    except ImportError:
        return False

    try:
        degree_u = int(ns_data["degree_u"])
        degree_v = int(ns_data["degree_v"])
        knots_u = ns_data["knots_u"]
        knots_v = ns_data["knots_v"]
        cps = ns_data["control_points"]  # [u][v]
        n_u = len(cps)
        n_v = len(cps[0]) if n_u > 0 else 0
        raw_w = ns_data.get("weights")
        weights = raw_w if raw_w is not None else [[1.0] * n_v for _ in range(n_u)]

        is_rational = any(
            abs(weights[i][j] - 1.0) > 1e-15
            for i in range(n_u)
            for j in range(n_v)
        )

        surf = rhino3dm.NurbsSurface.Create(3, is_rational, degree_u + 1, degree_v + 1, n_u, n_v)

        for i in range(n_u):
            for j in range(n_v):
                pt = cps[i][j]
                w = float(weights[i][j])
                surf.Points[(i, j)] = rhino3dm.Point4d(
                    float(pt[0]) * w,
                    float(pt[1]) * w,
                    float(pt[2]) * w,
                    w,
                )

        for i, k in enumerate(knots_u):
            surf.KnotsU[i] = float(k)
        for j, k in enumerate(knots_v):
            surf.KnotsV[j] = float(k)

        model.Objects.AddSurface(surf)
        return True
    except Exception:
        return False


def _add_from_rhino_json(model, kind: str, rhino_json: dict) -> bool:  # type: ignore[valid-type]
    """Re-materialise a geometry object from its rhino3dm Encode() JSON."""
    try:
        import rhino3dm  # noqa: PLC0415
    except ImportError:
        return False

    try:
        encoded = json.dumps(rhino_json)
        decoded = rhino3dm.CommonObject.Decode(encoded)
        if decoded is None:
            return False

        if kind == "feature":
            brep = rhino3dm.Brep.TryConvertBrep(decoded)
            if brep is not None:
                model.Objects.Add(brep)
                return True
            # decoded might already be a Brep subtype
            model.Objects.Add(decoded)
            return True
        elif kind == "mesh":
            if isinstance(decoded, rhino3dm.Mesh):
                model.Objects.Add(decoded)
                return True
        elif kind == "sketch":
            if hasattr(decoded, "PointAtStart"):
                model.Objects.AddCurve(decoded)
                return True
        elif kind == "surf":
            if isinstance(decoded, rhino3dm.Surface):
                model.Objects.AddSurface(decoded)
                return True

        # Generic fallback
        model.Objects.Add(decoded)
        return True
    except Exception:
        return False


def _add_point_fallback(model, content_json: dict) -> bool:  # type: ignore[valid-type]
    """Add a Point3d from x/y/z keys in content_json."""
    try:
        import rhino3dm  # noqa: PLC0415
    except ImportError:
        return False

    try:
        pt = rhino3dm.Point3d(
            float(content_json.get("x", 0)),
            float(content_json.get("y", 0)),
            float(content_json.get("z", 0)),
        )
        model.Objects.AddPoint(pt)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public: export_to_3dm
# ---------------------------------------------------------------------------


def export_to_3dm(
    objects: Sequence[dict[str, Any]],
    *,
    version: int = 7,
) -> bytes:
    """Convert a list of KerfObject dicts to a .3dm binary blob.

    Each entry in *objects* must be a dict with at minimum:

        {
            "kind":  "sketch" | "surf" | "feature" | "mesh" | "point",
            "content_json": { ... }   # see module docstring
        }

    Parameters
    ----------
    objects:
        Iterable of KerfObject dicts.
    version:
        .3dm file version to write (default 7).  Passed directly to
        ``rhino3dm.File3dm.Write(path, version)``.

    Returns
    -------
    bytes
        Raw .3dm binary suitable for writing to disk or uploading.

    Raises
    ------
    ImportError
        If rhino3dm is not installed.
    ValueError
        If *objects* is empty.
    """
    try:
        import rhino3dm  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "rhino3dm is required for 3DM export. "
            "Install it with: pip install rhino3dm"
        ) from exc

    if not objects:
        raise ValueError("objects must be a non-empty sequence")

    model = rhino3dm.File3dm()

    for obj in objects:
        kind = obj.get("kind", "")
        raw = obj.get("content_json") or obj.get("content") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}

        if not isinstance(raw, dict):
            continue

        # Strategy 1: structured NURBS curve
        if "nurbs_curve" in raw and kind in ("sketch", ""):
            _add_nurbs_curve(model, raw["nurbs_curve"])
            continue

        # Strategy 2: structured NURBS surface
        if "nurbs_surface" in raw and kind in ("surf", ""):
            _add_nurbs_surface(model, raw["nurbs_surface"])
            continue

        # Strategy 3: rhino3dm Encode() round-trip JSON
        rhino_json = raw.get("rhino_json")
        if rhino_json:
            _add_from_rhino_json(model, kind, rhino_json)
            continue

        # Strategy 4: fallback point
        if isinstance(raw, dict) and "x" in raw:
            _add_point_fallback(model, raw)
            continue

        # Strategy 5: point-kind with x/y/z at top level
        if kind == "point":
            _add_point_fallback(model, raw)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "export.3dm"
        model.Write(str(out_path), version)
        return out_path.read_bytes()


# ---------------------------------------------------------------------------
# Round-trip helpers exposed for testing
# ---------------------------------------------------------------------------


def _read_3dm_objects(data: bytes) -> list[Any]:
    """Read a .3dm binary and return a list of (geometry, attributes) pairs.

    Requires rhino3dm.
    """
    import rhino3dm  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "rt.3dm"
        p.write_bytes(data)
        model = rhino3dm.File3dm.Read(str(p))

    if model is None:
        raise RuntimeError("rhino3dm returned None while reading round-trip file")

    return [(obj.Geometry, obj.Attributes) for obj in model.Objects]


def _extract_nurbs_curve_cps(geom) -> list[list[float]]:
    """Extract Euclidean control points from a rhino3dm NurbsCurve."""
    pts = []
    for i in range(geom.Points.Count):
        p4 = geom.Points[i]
        w = p4.W if abs(p4.W) > 1e-15 else 1.0
        pts.append([p4.X / w, p4.Y / w, p4.Z / w])
    return pts


def _extract_nurbs_surface_cps(geom) -> list[list[list[float]]]:
    """Extract Euclidean control points from a rhino3dm NurbsSurface (2-D [u][v])."""
    nu = geom.Points.CountU
    nv = geom.Points.CountV
    grid: list[list[list[float]]] = []
    for i in range(nu):
        row: list[list[float]] = []
        for j in range(nv):
            p4 = geom.Points[(i, j)]
            w = p4.W if abs(p4.W) > 1e-15 else 1.0
            row.append([p4.X / w, p4.Y / w, p4.Z / w])
        grid.append(row)
    return grid
