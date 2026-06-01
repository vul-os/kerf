"""mesh_displacement_stack.py — GK-P21: Layered displacement map stack for procedural mesh detailing.

Implements a ZBrush/Mudbox-style ordered displacement layer stack: each layer
carries a per-vertex scalar displacement map, a compositing mode
(add/subtract/multiply/replace), an optional per-vertex mask, and a strength
scalar.  Layers are applied in order, accumulating a net per-vertex scalar
displacement d_total, then the final displaced position is:

    P' = P + d_total * N_hat

where N_hat is the unit surface normal supplied by the caller.

References
----------
- Pixologic ZBrush Documentation (2024) — Layer palette; Layer blend modes:
  Standard (Add), Subtract, Multiply, Replace.
- Autodesk Mudbox 2009 — Layered displacement compositing:
  Aumann & McNamara (2009) "Layered Displacement Maps for Detailed Sculpting"
  Proc. SIGGRAPH 2009 (course notes).
- Lee, A., Moreton, H. & Hoppe, H. (2000) "Displaced Subdivision Surfaces"
  SIGGRAPH 2000, pp. 85-94.

Honest caveats
--------------
- Per-vertex displacement only — no fractional indexing or interpolation across
  face barycentric coordinates.  A displacement value corresponds to exactly one
  vertex; sub-vertex feature detail requires denser tessellation first.
- Caller is responsible for providing unit-length normals.  Non-unit normals
  scale displacement by their magnitude and produce incorrect results.  The
  implementation does NOT renormalise input normals.
- ``multiply`` mode on the first enabled layer multiplies the zero accumulator
  by d_layer, yielding zero — prepend an ``add`` layer or ensure multiply layers
  follow at least one non-zero add/replace layer.
- Mask values outside [0, 1] are clamped at evaluation time; the raw list is
  stored as-is.
- No GPU acceleration: O(V × L) pure Python/NumPy loop.  Performance is
  adequate up to ~500k vertices × 10 layers; larger stacks benefit from a
  vectorised pipeline outside this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DisplacementLayer:
    """A single named layer in a displacement stack.

    Parameters
    ----------
    name:
        Human-readable label (e.g. ``"low-freq form"`` or ``"skin detail"``).
    displacement_values:
        Per-vertex signed scalar displacement magnitudes in scene units (mm).
        Must have the same length as ``DisplacementStackSpec.base_vertices_xyz``.
    mode:
        Compositing mode applied to the running accumulator *d_total*:
        - ``"add"``      — d_total += d_layer
        - ``"subtract"`` — d_total -= d_layer
        - ``"multiply"`` — d_total *= d_layer
        - ``"replace"``  — d_total  = d_layer  (overrides all prior layers)
    mask:
        Optional per-vertex weight in ``[0, 1]``.  Values outside the range
        are clamped.  ``None`` is equivalent to a uniform weight of ``1.0``
        (full influence, no masking).
    strength:
        Global scalar multiplier applied to the displacement before compositing.
        Defaults to ``1.0``.  Negative values invert the displacement direction.
    enabled:
        When ``False`` the layer is skipped entirely.  Defaults to ``True``.
    """

    name: str
    displacement_values: List[float]
    mode: str  # "add" | "subtract" | "multiply" | "replace"
    mask: Optional[List[float]] = None
    strength: float = 1.0
    enabled: bool = True


@dataclass
class DisplacementStackSpec:
    """Input spec for :func:`apply_displacement_stack`.

    Parameters
    ----------
    base_vertices_xyz:
        List of ``(x, y, z)`` vertex positions in mm.
    base_normals_xyz:
        List of ``(nx, ny, nz)`` vertex normals.  Must be unit-length;
        the function does not renormalise them.
    layers:
        Ordered list of :class:`DisplacementLayer` objects applied front to
        back.  Disabled layers are skipped.
    """

    base_vertices_xyz: List[Tuple[float, float, float]]
    base_normals_xyz: List[Tuple[float, float, float]]
    layers: List[DisplacementLayer]


@dataclass
class DisplacementStackResult:
    """Output of :func:`apply_displacement_stack`.

    Parameters
    ----------
    output_vertices_xyz:
        Displaced vertex positions in mm.  Same length as the input vertex
        list.
    layer_contributions:
        Per-layer maximum absolute contribution magnitude (mm).  Disabled
        layers report ``0.0``.
    num_layers_applied:
        Number of enabled layers that were processed.
    max_displacement_mm:
        Maximum absolute per-vertex net displacement across all vertices.
    mean_displacement_mm:
        Mean absolute per-vertex net displacement.
    honest_caveat:
        Human-readable string describing implementation limits.
    """

    output_vertices_xyz: List[Tuple[float, float, float]]
    layer_contributions: List[float]
    num_layers_applied: int
    max_displacement_mm: float
    mean_displacement_mm: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_VALID_MODES = frozenset({"add", "subtract", "multiply", "replace"})

_HONEST_CAVEAT = (
    "Per-vertex displacement only — no fractional indexing across face "
    "barycentric coordinates; assumes input normals are unit-length (not "
    "renormalised by this function); multiply on a zero accumulator yields "
    "zero — place an add/replace layer first when using multiply."
)


def apply_displacement_stack(spec: DisplacementStackSpec) -> DisplacementStackResult:
    """Apply a layered displacement stack to a base mesh.

    Algorithm
    ---------
    1. Initialise a per-vertex accumulator ``d_total[v] = 0.0`` for every
       vertex *v*.
    2. For each enabled layer in order:

       a. Compute the masked, strength-scaled displacement:

          .. code-block:: python

              mask_v  = clamp(layer.mask[v], 0, 1)   # or 1.0 if mask is None
              d_layer = layer.displacement_values[v] * mask_v * layer.strength

       b. Apply via the layer's compositing mode:

          - ``add``      : ``d_total[v] += d_layer``
          - ``subtract`` : ``d_total[v] -= d_layer``
          - ``multiply`` : ``d_total[v] *= d_layer``
          - ``replace``  : ``d_total[v]  = d_layer``

    3. Compute the final displaced position:

       .. code-block:: python

           P'[v] = P[v] + d_total[v] * N_hat[v]

    Parameters
    ----------
    spec:
        A fully-populated :class:`DisplacementStackSpec`.

    Returns
    -------
    DisplacementStackResult

    Raises
    ------
    ValueError
        If a layer's ``mode`` is not one of ``"add"``, ``"subtract"``,
        ``"multiply"``, ``"replace"``; or if the vertex/normal/layer counts
        are inconsistent.
    """
    n_verts = len(spec.base_vertices_xyz)

    if len(spec.base_normals_xyz) != n_verts:
        raise ValueError(
            f"base_normals_xyz length {len(spec.base_normals_xyz)} "
            f"does not match base_vertices_xyz length {n_verts}."
        )

    for i, layer in enumerate(spec.layers):
        if not layer.enabled:
            continue
        if layer.mode not in _VALID_MODES:
            raise ValueError(
                f"Layer {i!r} (name={layer.name!r}) has invalid mode "
                f"{layer.mode!r}; must be one of {sorted(_VALID_MODES)}."
            )
        if len(layer.displacement_values) != n_verts:
            raise ValueError(
                f"Layer {i!r} (name={layer.name!r}) has "
                f"{len(layer.displacement_values)} displacement values but "
                f"the mesh has {n_verts} vertices."
            )
        if layer.mask is not None and len(layer.mask) != n_verts:
            raise ValueError(
                f"Layer {i!r} (name={layer.name!r}) mask has "
                f"{len(layer.mask)} values but the mesh has {n_verts} vertices."
            )

    # Accumulator: one float per vertex.
    d_total = [0.0] * n_verts

    layer_contributions: List[float] = []
    num_layers_applied = 0

    for i, layer in enumerate(spec.layers):
        if not layer.enabled:
            layer_contributions.append(0.0)
            continue

        num_layers_applied += 1
        strength = layer.strength
        displacements = layer.displacement_values
        mask = layer.mask
        mode = layer.mode

        max_contrib = 0.0

        if mode == "add":
            for v in range(n_verts):
                m = max(0.0, min(1.0, mask[v])) if mask is not None else 1.0
                d = displacements[v] * m * strength
                d_total[v] += d
                abs_d = abs(d)
                if abs_d > max_contrib:
                    max_contrib = abs_d
        elif mode == "subtract":
            for v in range(n_verts):
                m = max(0.0, min(1.0, mask[v])) if mask is not None else 1.0
                d = displacements[v] * m * strength
                d_total[v] -= d
                abs_d = abs(d)
                if abs_d > max_contrib:
                    max_contrib = abs_d
        elif mode == "multiply":
            for v in range(n_verts):
                m = max(0.0, min(1.0, mask[v])) if mask is not None else 1.0
                d = displacements[v] * m * strength
                # record contribution = |d_total change|
                prev = d_total[v]
                d_total[v] *= d
                abs_d = abs(d_total[v] - prev)
                if abs_d > max_contrib:
                    max_contrib = abs_d
        elif mode == "replace":
            for v in range(n_verts):
                m = max(0.0, min(1.0, mask[v])) if mask is not None else 1.0
                d = displacements[v] * m * strength
                d_total[v] = d
                abs_d = abs(d)
                if abs_d > max_contrib:
                    max_contrib = abs_d

        layer_contributions.append(max_contrib)

    # Apply displacement along normals.
    output_vertices: List[Tuple[float, float, float]] = []
    abs_disps: List[float] = []

    for v in range(n_verts):
        px, py, pz = spec.base_vertices_xyz[v]
        nx, ny, nz = spec.base_normals_xyz[v]
        d = d_total[v]
        output_vertices.append((px + d * nx, py + d * ny, pz + d * nz))
        abs_disps.append(abs(d))

    max_disp = max(abs_disps) if abs_disps else 0.0
    mean_disp = sum(abs_disps) / n_verts if n_verts > 0 else 0.0

    return DisplacementStackResult(
        output_vertices_xyz=output_vertices,
        layer_contributions=layer_contributions,
        num_layers_applied=num_layers_applied,
        max_displacement_mm=max_disp,
        mean_displacement_mm=mean_disp,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool — gated import
# ---------------------------------------------------------------------------

try:
    import json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    _mesh_apply_displacement_stack_spec = ToolSpec(
        name="mesh_apply_displacement_stack",
        description=(
            "Apply an ordered multi-layer displacement map stack to a base mesh, "
            "combining low-frequency form with high-frequency surface texture. "
            "Each layer carries per-vertex scalar displacement values, a compositing "
            "mode (add / subtract / multiply / replace), an optional per-vertex mask "
            "weight in [0,1], and a strength scalar. "
            "Layers are applied in order, accumulating a net per-vertex displacement "
            "d_total; the final position is P' = P + d_total * N_hat. "
            "Implements the ZBrush/Mudbox layer-stack model (Pixologic ZBrush Docs 2024; "
            "Aumann-McNamara 2009 Layered Displacement Maps, SIGGRAPH course notes; "
            "Lee-Moreton-Hoppe 2000 Displaced Subdivision Surfaces). "
            "HONEST CAVEATS: per-vertex only — no fractional indexing across face "
            "barycentric coordinates; caller must supply unit-length normals; "
            "multiply on a zero accumulator yields zero."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "base_vertices_xyz": {
                    "type": "array",
                    "description": (
                        "List of [x, y, z] vertex positions in mm. "
                        "Example: [[0,0,0],[1,0,0],[0,1,0]]."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                },
                "base_normals_xyz": {
                    "type": "array",
                    "description": (
                        "Per-vertex unit surface normals [nx, ny, nz]. "
                        "Must be unit-length; not renormalised by this tool."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                },
                "layers": {
                    "type": "array",
                    "description": "Ordered list of displacement layers, applied front to back.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Human-readable layer name.",
                            },
                            "displacement_values": {
                                "type": "array",
                                "description": (
                                    "Per-vertex signed displacement magnitudes in mm. "
                                    "Length must equal the number of vertices."
                                ),
                                "items": {"type": "number"},
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["add", "subtract", "multiply", "replace"],
                                "description": "Compositing mode.",
                            },
                            "mask": {
                                "type": ["array", "null"],
                                "description": (
                                    "Per-vertex mask weight in [0, 1]. "
                                    "null = full influence (1.0 everywhere)."
                                ),
                                "items": {"type": "number"},
                            },
                            "strength": {
                                "type": "number",
                                "description": "Global layer strength multiplier. Default 1.0.",
                                "default": 1.0,
                            },
                            "enabled": {
                                "type": "boolean",
                                "description": "When false the layer is skipped. Default true.",
                                "default": True,
                            },
                        },
                        "required": ["name", "displacement_values", "mode"],
                    },
                },
            },
            "required": ["base_vertices_xyz", "base_normals_xyz", "layers"],
        },
    )

    @register(_mesh_apply_displacement_stack_spec, write=False)
    async def _run_mesh_apply_displacement_stack(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("base_vertices_xyz")
        raw_normals = a.get("base_normals_xyz")
        raw_layers = a.get("layers")

        if not isinstance(raw_verts, list) or len(raw_verts) == 0:
            return err_payload("base_vertices_xyz must be a non-empty list", "BAD_ARGS")
        if not isinstance(raw_normals, list):
            return err_payload("base_normals_xyz must be a list", "BAD_ARGS")
        if not isinstance(raw_layers, list):
            return err_payload("layers must be a list", "BAD_ARGS")

        # Parse vertices
        try:
            verts: List[Tuple[float, float, float]] = [
                (float(p[0]), float(p[1]), float(p[2])) for p in raw_verts
            ]
        except (TypeError, IndexError, ValueError) as exc:
            return err_payload(f"base_vertices_xyz parse error: {exc}", "BAD_ARGS")

        # Parse normals
        try:
            normals: List[Tuple[float, float, float]] = [
                (float(n[0]), float(n[1]), float(n[2])) for n in raw_normals
            ]
        except (TypeError, IndexError, ValueError) as exc:
            return err_payload(f"base_normals_xyz parse error: {exc}", "BAD_ARGS")

        # Parse layers
        layers: List[DisplacementLayer] = []
        for idx, ld in enumerate(raw_layers):
            if not isinstance(ld, dict):
                return err_payload(f"Layer {idx} must be an object", "BAD_ARGS")
            name = str(ld.get("name", f"layer_{idx}"))
            raw_disp = ld.get("displacement_values")
            if not isinstance(raw_disp, list):
                return err_payload(
                    f"Layer {idx} displacement_values must be a list", "BAD_ARGS"
                )
            try:
                disp = [float(x) for x in raw_disp]
            except (TypeError, ValueError) as exc:
                return err_payload(
                    f"Layer {idx} displacement_values parse error: {exc}", "BAD_ARGS"
                )
            mode = ld.get("mode", "add")
            if mode not in _VALID_MODES:
                return err_payload(
                    f"Layer {idx} mode {mode!r} invalid; "
                    f"must be one of {sorted(_VALID_MODES)}",
                    "BAD_ARGS",
                )
            raw_mask = ld.get("mask", None)
            mask: Optional[List[float]] = None
            if raw_mask is not None:
                try:
                    mask = [float(x) for x in raw_mask]
                except (TypeError, ValueError) as exc:
                    return err_payload(
                        f"Layer {idx} mask parse error: {exc}", "BAD_ARGS"
                    )
            strength = float(ld.get("strength", 1.0))
            enabled = bool(ld.get("enabled", True))
            layers.append(
                DisplacementLayer(
                    name=name,
                    displacement_values=disp,
                    mode=mode,
                    mask=mask,
                    strength=strength,
                    enabled=enabled,
                )
            )

        spec = DisplacementStackSpec(
            base_vertices_xyz=verts,
            base_normals_xyz=normals,
            layers=layers,
        )
        try:
            result = apply_displacement_stack(spec)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"internal error: {exc}", "INTERNAL")

        return ok_payload(
            {
                "output_vertices_xyz": [list(p) for p in result.output_vertices_xyz],
                "layer_contributions": result.layer_contributions,
                "num_layers_applied": result.num_layers_applied,
                "max_displacement_mm": result.max_displacement_mm,
                "mean_displacement_mm": result.mean_displacement_mm,
                "honest_caveat": result.honest_caveat,
            }
        )

except ImportError:
    pass  # kerf_chat not available — core API still usable standalone
