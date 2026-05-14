"""
assembly.py — T5 Multi-Body .FCStd → .assembly

Detects whether a document contains multiple ``PartDesign::Body`` objects and,
if so, emits a Kerf ``.assembly`` payload with one Component per Body.

Usage::

    from kerf_imports.freecad.assembly import build_assembly

    result = build_assembly(doc, feature_payloads)
    if result is not None:
        # result["components"]      — list of component dicts
        # result["freecad_ref"]     — { "program_version": ..., "bodies": [...] }
    else:
        # single-body document — no assembly file needed

Single-Body documents: ``build_assembly`` returns ``None`` — the caller creates
only the ``.feature`` file from T4 and no ``.assembly``.

Multi-Body documents: ``build_assembly`` returns the ``.assembly`` payload.

Transform calculation:
  FreeCAD ``Placement`` stores position as ``(Px, Py, Pz)`` and rotation as a
  quaternion ``(Q0, Q1, Q2, Q3)`` where Q0 is the scalar (w) part:
    - FreeCAD: (Q0=w, Q1=x, Q2=y, Q3=z)  (confirmed from App/Placement.cpp)
  The 4×4 transform matrix is built as rotation-from-quaternion + translation.
"""
from __future__ import annotations

import math
from typing import Any

from .types import FCStdDocument, FCStdObject
from .brep_importer import FeaturePayload


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_assembly(
    doc: FCStdDocument,
    feature_payloads: list[FeaturePayload] | None = None,
) -> dict[str, Any] | None:
    """
    Build a Kerf ``.assembly`` payload from a multi-Body FCStd document.

    Parameters
    ----------
    doc :
        Parsed :class:`~kerf_imports.freecad.types.FCStdDocument`.
    feature_payloads :
        The :class:`~kerf_imports.freecad.brep_importer.FeaturePayload` list
        returned by T4's :func:`~kerf_imports.freecad.features.build_metadata_tree`.
        Used to resolve ``body_name → .feature`` filename.  If ``None``, the
        names are inferred from the Body labels.

    Returns
    -------
    dict or None
        ``.assembly`` payload dict if the document has > 1 Body; ``None``
        for single-Body documents.
    """
    bodies = doc.objects_by_type("PartDesign::Body")

    if len(bodies) <= 1:
        return None  # Single-body: no assembly file

    # Index feature payloads by body_name for fast lookup
    payload_by_name: dict[str, FeaturePayload] = {}
    if feature_payloads:
        for fp in feature_payloads:
            payload_by_name[fp.body_name] = fp

    components: list[dict[str, Any]] = []

    for body in bodies:
        label = body.label or body.name

        # Resolve the .feature file path for this body
        fp = payload_by_name.get(body.name)
        feature_path = f"/{fp.body_label}.feature" if fp else f"/{label}.feature"

        # Extract the 4×4 transform from the body's Placement
        placement = body.properties.get("Placement")
        transform = _placement_to_matrix(placement)

        component: dict[str, Any] = {
            "id": f"comp-{body.name}",
            "name": label,
            "feature_path": feature_path,
            "transform": transform,
            "freecad_ref": {
                "type": body.type,
                "name": body.name,
                "label": label,
            },
        }
        components.append(component)

    return {
        "components": components,
        "freecad_ref": {
            "program_version": doc.program_version,
            "schema_version": doc.schema_version,
            "bodies": [b.name for b in bodies],
        },
    }


# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------

def _placement_to_matrix(placement: dict | None) -> list[list[float]]:
    """
    Convert a FreeCAD ``Placement`` property dict to a 4×4 row-major matrix.

    FreeCAD stores:
      - ``Px``, ``Py``, ``Pz`` — translation (mm)
      - ``Q0`` (w), ``Q1`` (x), ``Q2`` (y), ``Q3`` (z) — unit quaternion

    If the placement is missing or has no rotation data, returns the identity
    matrix.

    Returns
    -------
    list[list[float]]
        4×4 row-major matrix, i.e. ``M[row][col]``.
    """
    if not placement or not isinstance(placement, dict):
        return _identity()

    px = float(placement.get("Px", 0) or 0)
    py = float(placement.get("Py", 0) or 0)
    pz = float(placement.get("Pz", 0) or 0)

    # Quaternion (FreeCAD convention: Q0=w, Q1=x, Q2=y, Q3=z)
    if "Q0" in placement:
        qw = float(placement.get("Q0", 1) or 1)
        qx = float(placement.get("Q1", 0) or 0)
        qy = float(placement.get("Q2", 0) or 0)
        qz = float(placement.get("Q3", 0) or 0)
        rot = _quat_to_rotation(qw, qx, qy, qz)
    elif "Ax" in placement:
        # Axis + angle form
        ax = float(placement.get("Ax", 0) or 0)
        ay = float(placement.get("Ay", 0) or 0)
        az = float(placement.get("Az", 1) or 1)
        angle = float(placement.get("A", 0) or 0)
        qw, qx, qy, qz = _axis_angle_to_quat(ax, ay, az, angle)
        rot = _quat_to_rotation(qw, qx, qy, qz)
    else:
        rot = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    # Assemble 4×4
    m = [
        [rot[0][0], rot[0][1], rot[0][2], px],
        [rot[1][0], rot[1][1], rot[1][2], py],
        [rot[2][0], rot[2][1], rot[2][2], pz],
        [0.0,       0.0,       0.0,       1.0],
    ]
    return m


def _identity() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _quat_to_rotation(
    w: float, x: float, y: float, z: float
) -> list[list[float]]:
    """
    Convert a unit quaternion (w, x, y, z) to a 3×3 rotation matrix.

    Uses the standard formula:
      R = I + 2w·[k]× + 2·[k]×²
    where [k]× is the skew-symmetric matrix of (x, y, z).
    """
    # Normalise to guard against numerical drift
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    w, x, y, z = w / n, x / n, y / n, z / n

    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    return [
        [1 - 2 * (yy + zz),   2 * (xy - wz),    2 * (xz + wy)],
        [2 * (xy + wz),        1 - 2 * (xx + zz), 2 * (yz - wx)],
        [2 * (xz - wy),        2 * (yz + wx),     1 - 2 * (xx + yy)],
    ]


def _axis_angle_to_quat(
    ax: float, ay: float, az: float, angle_rad: float
) -> tuple[float, float, float, float]:
    """Convert axis + angle (radians) to quaternion (w, x, y, z)."""
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n < 1e-12:
        return 1.0, 0.0, 0.0, 0.0
    ax, ay, az = ax / n, ay / n, az / n
    s = math.sin(angle_rad / 2)
    return math.cos(angle_rad / 2), ax * s, ay * s, az * s
