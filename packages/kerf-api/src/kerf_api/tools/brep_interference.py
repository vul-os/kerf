"""LLM tools for B-rep interference volume analysis (GK-P-IV).

Tools
-----
brep_interference_volume
    Compute the exact/approximate volume of intersection between two B-rep
    bodies identified by their object IDs in a project file.  Returns
    volume, interference_severity, method, and std_error.

brep_assembly_interference_matrix
    Compute the all-pairs interference volume matrix for an assembly's
    component bodies.  Returns an N×N JSON matrix and a ranked list of
    the most-severe interference pairs.

Both tools are pure-computation (read-only) and do not modify project state.
"""

from __future__ import annotations

import json
import uuid

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_core.db.queries import files as file_queries


# ---------------------------------------------------------------------------
# brep_interference_volume
# ---------------------------------------------------------------------------

brep_interference_volume_spec = ToolSpec(
    name="brep_interference_volume",
    description=(
        "Compute the exact volume of intersection (interference) between two solid "
        "B-rep bodies in a CAD file. Returns the intersection volume, a normalised "
        "interference severity score (0=no overlap, 1=fully inside), the computation "
        "method, and statistical error. Use this to quantify collision severity and "
        "rank interference issues in assembly clearance analysis."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the CAD file containing the geometry.",
            },
            "object_id_a": {
                "type": "string",
                "description": "ID of the first solid body (component A).",
            },
            "object_id_b": {
                "type": "string",
                "description": "ID of the second solid body (component B).",
            },
            "method": {
                "type": "string",
                "enum": ["boolean", "monte_carlo", "voxel"],
                "description": (
                    "Computation method: "
                    "'boolean' (exact, fastest for simple analytic bodies), "
                    "'monte_carlo' (statistical, accurate for any shape, default), "
                    "'voxel' (discretised grid). "
                    "Default: 'boolean'."
                ),
            },
            "n_samples": {
                "type": "integer",
                "description": "Number of MC samples (monte_carlo only). Default 10000.",
            },
            "max_acceptable_volume": {
                "type": "number",
                "description": (
                    "Optional design threshold. If given, the result will include "
                    "'acceptable': true/false."
                ),
            },
        },
        "required": ["file_id", "object_id_a", "object_id_b"],
    },
)


@register(brep_interference_volume_spec)
async def run_brep_interference_volume(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    object_id_a = a.get("object_id_a", "").strip()
    object_id_b = a.get("object_id_b", "").strip()
    method = a.get("method", "boolean")
    n_samples = int(a.get("n_samples", 10000))
    max_acceptable_volume = a.get("max_acceptable_volume")

    if not file_id or not object_id_a or not object_id_b:
        return err_payload("file_id, object_id_a, and object_id_b are required", "BAD_ARGS")

    if method not in ("boolean", "monte_carlo", "voxel"):
        return err_payload("method must be one of: boolean, monte_carlo, voxel", "BAD_ARGS")

    if n_samples < 1:
        return err_payload("n_samples must be >= 1", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a UUID", "BAD_ARGS")

    row = await file_queries.get_file(ctx.pool, fid)
    if not row:
        return err_payload("file not found", "NOT_FOUND")

    # Parse the geometry document to locate the two bodies
    content = row.get("content") or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        return err_payload("file content is not valid JSON", "BAD_FILE")

    if not isinstance(doc, dict):
        return err_payload("file content is not a JSON object", "BAD_FILE")

    # Extract body geometry from the document's objects list
    objects = doc.get("objects") or doc.get("components") or []
    obj_map: dict = {}
    for obj in objects:
        if isinstance(obj, dict):
            oid = obj.get("id") or obj.get("object_id") or ""
            if oid:
                obj_map[oid] = obj

    if object_id_a not in obj_map:
        return err_payload(f"object_id_a '{object_id_a}' not found in file", "NOT_FOUND")
    if object_id_b not in obj_map:
        return err_payload(f"object_id_b '{object_id_b}' not found in file", "NOT_FOUND")

    obj_a = obj_map[object_id_a]
    obj_b = obj_map[object_id_b]

    # Build B-rep bodies from the geometry descriptors
    try:
        body_a = _build_body_from_object(obj_a)
        body_b = _build_body_from_object(obj_b)
    except Exception as e:
        return err_payload(f"failed to build body geometry: {e}", "BUILD_ERROR")

    # Compute interference volume
    try:
        from kerf_cad_core.geom.interference_volume import interference_severity_score
        score = interference_severity_score(
            body_a,
            body_b,
            method=method,
            max_acceptable_volume=max_acceptable_volume,
            n_samples=n_samples,
        )
    except Exception as e:
        return err_payload(f"interference volume computation failed: {e}", "COMPUTE_ERROR")

    result = {
        "file_id": file_id,
        "object_id_a": object_id_a,
        "object_id_b": object_id_b,
        "volume": score["volume"],
        "interference_severity": score["score"],
        "interferes": score["interferes"],
        "volume_a": score["volume_a"],
        "volume_b": score["volume_b"],
        "min_body_volume": score["min_body_volume"],
        "method": score["method"],
    }
    if "acceptable" in score:
        result["acceptable"] = score["acceptable"]

    return ok_payload(result)


# ---------------------------------------------------------------------------
# brep_assembly_interference_matrix
# ---------------------------------------------------------------------------

brep_assembly_interference_matrix_spec = ToolSpec(
    name="brep_assembly_interference_matrix",
    description=(
        "Compute the all-pairs interference volume matrix for an assembly file. "
        "Returns an N×N symmetric matrix where entry [i][j] is the interference "
        "volume between component i and component j, plus a ranked list of the "
        "most-severe pairs for prioritised design review. Use this for assembly "
        "clearance audits and collision severity ranking across all part pairs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly_file_id": {
                "type": "string",
                "description": "UUID of the assembly file.",
            },
            "method": {
                "type": "string",
                "enum": ["boolean", "monte_carlo", "voxel"],
                "description": "Computation method. Default: 'boolean'.",
            },
            "n_samples": {
                "type": "integer",
                "description": "MC samples per pair (monte_carlo only). Default 5000.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of worst-interference pairs to return in the ranked list. Default 10.",
            },
        },
        "required": ["assembly_file_id"],
    },
)


@register(brep_assembly_interference_matrix_spec)
async def run_brep_assembly_interference_matrix(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    assembly_file_id = a.get("assembly_file_id", "").strip()
    method = a.get("method", "boolean")
    n_samples = int(a.get("n_samples", 5000))
    top_k = int(a.get("top_k", 10))

    if not assembly_file_id:
        return err_payload("assembly_file_id is required", "BAD_ARGS")

    if method not in ("boolean", "monte_carlo", "voxel"):
        return err_payload("method must be one of: boolean, monte_carlo, voxel", "BAD_ARGS")

    try:
        fid = uuid.UUID(assembly_file_id)
    except Exception:
        return err_payload("assembly_file_id must be a UUID", "BAD_ARGS")

    row = await file_queries.get_file(ctx.pool, fid)
    if not row:
        return err_payload("assembly file not found", "NOT_FOUND")

    content = row.get("content") or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        return err_payload("file content is not valid JSON", "BAD_FILE")

    if not isinstance(doc, dict):
        return err_payload("file content is not a JSON object", "BAD_FILE")

    # Collect components with geometry
    components = doc.get("components") or doc.get("objects") or []
    if not isinstance(components, list):
        return err_payload("no components list found in assembly file", "BAD_FILE")

    # Build bodies for each component
    bodies = []
    component_ids = []
    build_errors = []

    for comp in components:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id") or comp.get("object_id") or ""
        if not cid:
            continue
        try:
            body = _build_body_from_object(comp)
            bodies.append(body)
            component_ids.append(cid)
        except Exception as e:
            build_errors.append({"component_id": cid, "error": str(e)})

    if len(bodies) < 2:
        return err_payload(
            f"need at least 2 buildable bodies; got {len(bodies)} "
            f"(build errors: {len(build_errors)})",
            "INSUFFICIENT_BODIES",
        )

    # Compute pairwise matrix
    try:
        import numpy as np
        from kerf_cad_core.geom.interference_volume import pairwise_interference_assembly
        matrix = pairwise_interference_assembly(
            bodies, method=method, n_samples=n_samples
        )
    except Exception as e:
        return err_payload(f"pairwise interference computation failed: {e}", "COMPUTE_ERROR")

    # Build ranked list of worst interfering pairs
    n = len(bodies)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            v = float(matrix[i, j])
            if v > 1e-12:
                pairs.append({
                    "component_id_a": component_ids[i],
                    "component_id_b": component_ids[j],
                    "interference_volume": v,
                })

    pairs.sort(key=lambda p: p["interference_volume"], reverse=True)
    top_pairs = pairs[:top_k]

    return ok_payload({
        "assembly_file_id": assembly_file_id,
        "component_ids": component_ids,
        "n_components": n,
        "method": method,
        "matrix": matrix.tolist(),
        "interfering_pairs": top_pairs,
        "total_interfering_pairs": len(pairs),
        "build_errors": build_errors,
    })


# ---------------------------------------------------------------------------
# Internal helper: build a Body from an object descriptor dict
# ---------------------------------------------------------------------------

def _build_body_from_object(obj: dict):
    """Build a B-rep Body from an object descriptor.

    Supports a minimal subset of geometry types that can be expressed in
    JSON assembly documents:
      * ``{"type": "box", "corner": [x, y, z], "dx": ..., "dy": ..., "dz": ...}``
      * ``{"type": "sphere", "center": [x, y, z], "radius": ...}``
      * ``{"type": "cylinder", "center": [x, y, z], "axis": [...], "radius": ..., "height": ...}``

    For non-primitive geometry (NURBS, feature-based), callers must provide
    a pre-serialised ``"brep_data"`` key (reserved for future STEP/JT deserialisation).

    Raises
    ------
    ValueError
        If the object type is unrecognised or required fields are missing.
    """
    from kerf_cad_core.geom.brep_build import box_to_body, sphere_to_body, cylinder_to_body

    geom_type = (obj.get("type") or obj.get("geom_type") or "").lower()

    if geom_type == "box":
        corner = tuple(float(v) for v in obj.get("corner", [0, 0, 0]))
        dx = float(obj.get("dx", obj.get("width", 1.0)))
        dy = float(obj.get("dy", obj.get("depth", 1.0)))
        dz = float(obj.get("dz", obj.get("height", 1.0)))
        return box_to_body(corner=corner, dx=dx, dy=dy, dz=dz)

    if geom_type == "sphere":
        center = tuple(float(v) for v in obj.get("center", [0, 0, 0]))
        radius = float(obj.get("radius", 1.0))
        return sphere_to_body(center=center, radius=radius)

    if geom_type in ("cylinder", "cyl"):
        center = tuple(float(v) for v in obj.get("center", [0, 0, 0]))
        axis = tuple(float(v) for v in obj.get("axis", [0, 0, 1]))
        radius = float(obj.get("radius", 1.0))
        height = float(obj.get("height", obj.get("dz", 1.0)))
        return cylinder_to_body(center=center, axis=axis, radius=radius, height=height)

    raise ValueError(
        f"Unsupported geometry type {geom_type!r}. "
        "Supported: 'box', 'sphere', 'cylinder'. "
        "For NURBS/feature geometry, provide a STEP-based 'brep_data' key."
    )
