"""kerf_cad_core.geom.tools — LLM tool wrappers for geometry-kernel mass properties.

Registered tools
----------------
  brep_centroid_density_field  — volume-weighted centroid + inertia for a
                                  B-rep body with a spatially-varying density
                                  field (functionally graded materials, variable
                                  infill, shell-dense 3D prints).

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Mortenson, M.E. (1985) *Geometric Modeling* §11.5 — compound density
integration via volume integral.
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.geom.brep import make_box, make_sphere, make_cylinder
from kerf_cad_core.geom.volume_weighted_centroid import (
    compute_centroid_density_field,
    compute_inertia_density_field,
    functionally_graded_centroid,
)


# ---------------------------------------------------------------------------
# Tool: brep_centroid_density_field
# ---------------------------------------------------------------------------

_brep_centroid_density_field_spec = ToolSpec(
    name="brep_centroid_density_field",
    description=(
        "Compute the volume-weighted centroid and (optionally) the inertia "
        "tensor of a B-rep body under a spatially-varying density field.\n"
        "\n"
        "Use cases:\n"
        "  - Functionally-graded materials (FGM): density varies continuously\n"
        "    across the body (e.g. ceramic→metal gradient).\n"
        "  - 3D-printed parts: shell-dense outer skin + lightweight infill core.\n"
        "  - Radially graded parts (e.g. soft inner / hard outer composites).\n"
        "  - Any body where the centre of mass differs from the geometric centroid.\n"
        "\n"
        "Body shapes supported:\n"
        "  box, sphere, cylinder (primitive shapes created internally for analysis).\n"
        "\n"
        "Density field kinds:\n"
        "  'linear_z'   — ρ(z) = ρ_0 · (1 + α·(z−z_lo)/L); density gradient\n"
        "                 along Z axis. alpha>0 → heavier at top, alpha<0 → heavier\n"
        "                 at bottom. Analytical z_centroid = (2/3)·L when ρ(z)=z.\n"
        "  'shell_dense' — dense shell + light core (3D-print topology);\n"
        "                  centroid stays at geometric centre for symmetric bodies;\n"
        "                  total mass < uniform-density body.\n"
        "  'radial'     — ρ(r) = ρ_max/(1+r/R)²; soft-inner/hard-outer radial\n"
        "                 gradient from geometric centroid.\n"
        "\n"
        "Also returns the full inertia tensor when compute_inertia=true.\n"
        "\n"
        "Returns centroid [x,y,z], total_mass, std_error, samples_used,\n"
        "and optionally inertia_tensor (3×3 list).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "body_kind": {
                "type": "string",
                "enum": ["box", "sphere", "cylinder"],
                "description": (
                    "Primitive body type to analyse. "
                    "'box' (default) — axis-aligned box; "
                    "'sphere' — sphere; 'cylinder' — Z-axis cylinder."
                ),
            },
            "size": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": (
                    "For box: [lx, ly, lz] side lengths (default [1,1,1]). "
                    "For sphere: [radius, _, _] (only first element used). "
                    "For cylinder: [radius, height, _] (first two used)."
                ),
            },
            "density_func_kind": {
                "type": "string",
                "enum": ["linear_z", "shell_dense", "radial"],
                "description": "Density field type (default 'linear_z').",
            },
            "rho_0": {
                "type": "number",
                "description": "Base density for linear_z (default 1.0).",
            },
            "alpha": {
                "type": "number",
                "description": (
                    "Gradient coefficient for linear_z (default 1.0). "
                    "alpha=1 → density doubles from bottom to top."
                ),
            },
            "rho_shell": {
                "type": "number",
                "description": "Shell density for shell_dense (default 2.0).",
            },
            "rho_core": {
                "type": "number",
                "description": "Core density for shell_dense (default 0.5).",
            },
            "shell_thickness_fraction": {
                "type": "number",
                "description": (
                    "Shell thickness as fraction of bounding-box diagonal "
                    "for shell_dense (default 0.1)."
                ),
            },
            "rho_max": {
                "type": "number",
                "description": "Peak density for radial (default 1.0).",
            },
            "R_fraction": {
                "type": "number",
                "description": (
                    "Decay length as fraction of bounding-box half-diagonal "
                    "for radial (default 0.5)."
                ),
            },
            "n_samples": {
                "type": "integer",
                "description": (
                    "Monte Carlo candidate samples (default 2000). "
                    "Increase for lower std_error."
                ),
            },
            "compute_inertia": {
                "type": "boolean",
                "description": (
                    "If true, also compute and return the full 3×3 inertia tensor "
                    "(default false; uses n_samples×5 for higher accuracy)."
                ),
            },
            "seed": {
                "type": "integer",
                "description": "Random seed for reproducible results (optional).",
            },
        },
        "required": [],
    },
)


def _make_body(body_kind: str, size: list):
    """Construct a primitive body for the tool."""
    s = size if size else [1.0, 1.0, 1.0]
    if body_kind == "sphere":
        r = float(s[0]) if s else 1.0
        return make_sphere(center=(0, 0, 0), radius=r)
    if body_kind == "cylinder":
        r = float(s[0]) if len(s) >= 1 else 1.0
        h = float(s[1]) if len(s) >= 2 else 1.0
        return make_cylinder(center=(0, 0, 0), axis=(0, 0, 1), radius=r, height=h)
    # default: box
    lx = float(s[0]) if len(s) >= 1 else 1.0
    ly = float(s[1]) if len(s) >= 2 else 1.0
    lz = float(s[2]) if len(s) >= 3 else 1.0
    return make_box(origin=(0, 0, 0), size=(lx, ly, lz))


@register(_brep_centroid_density_field_spec, write=False)
async def run_brep_centroid_density_field(ctx: ProjectCtx, args: bytes) -> str:
    import numpy as np

    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    body_kind = a.get("body_kind", "box")
    if body_kind not in ("box", "sphere", "cylinder"):
        return err_payload(f"body_kind must be 'box', 'sphere', or 'cylinder'; got {body_kind!r}", "BAD_ARGS")

    density_kind = a.get("density_func_kind", "linear_z")
    if density_kind not in ("linear_z", "shell_dense", "radial"):
        return err_payload(
            f"density_func_kind must be 'linear_z', 'shell_dense', or 'radial'; got {density_kind!r}",
            "BAD_ARGS",
        )

    n_samples = int(a.get("n_samples", 2000))
    if n_samples < 1:
        return err_payload("n_samples must be >= 1", "BAD_ARGS")

    seed = a.get("seed")
    rng = np.random.default_rng(seed)

    try:
        body = _make_body(body_kind, a.get("size", [1.0, 1.0, 1.0]))
    except Exception as exc:
        return err_payload(f"failed to create body: {exc}", "BODY_BUILD_ERROR")

    # Resolve bounding box for auto-params
    from kerf_cad_core.geom.sdf import _body_bbox
    lo, hi = _body_bbox(body, n_uv=12)
    diag = float(np.linalg.norm(hi - lo))

    # Build kwargs
    kwargs: dict = {
        "density_func_kind": density_kind,
        "n_samples": n_samples,
        "rng": rng,
    }
    if "rho_0" in a:
        kwargs["rho_0"] = float(a["rho_0"])
    if "alpha" in a:
        kwargs["alpha"] = float(a["alpha"])
    if "rho_shell" in a:
        kwargs["rho_shell"] = float(a["rho_shell"])
    if "rho_core" in a:
        kwargs["rho_core"] = float(a["rho_core"])
    if "shell_thickness_fraction" in a:
        kwargs["shell_thickness"] = float(a["shell_thickness_fraction"]) * diag
    if "rho_max" in a:
        kwargs["rho_max"] = float(a["rho_max"])
    if "R_fraction" in a:
        kwargs["R"] = float(a["R_fraction"]) * diag / 2.0

    try:
        result = functionally_graded_centroid(body, **kwargs)
    except Exception as exc:
        return err_payload(f"centroid computation failed: {exc}", "COMPUTE_ERROR")

    payload: dict = {
        "centroid": result.centroid.tolist(),
        "total_mass": result.total_mass,
        "std_error": result.std_error,
        "samples_used": result.samples_used,
        "density_func_kind": density_kind,
        "body_kind": body_kind,
    }

    if a.get("compute_inertia", False):
        try:
            from kerf_cad_core.geom.volume_weighted_centroid import (
                compute_inertia_density_field,
                functionally_graded_centroid as _fgc,
            )
            # Re-use the density field built inside functionally_graded_centroid
            # by running inertia with same kind — rebuild rng from same seed
            rng2 = np.random.default_rng(seed)
            inertia_kwargs = dict(kwargs)
            inertia_kwargs["n_samples"] = n_samples * 5
            inertia_kwargs["rng"] = rng2
            ir = _fgc(body, **inertia_kwargs)
            # Re-run proper inertia via compute_inertia_density_field
            # We need the actual density_field callable; rebuild it
            from kerf_cad_core.geom.sdf import _body_bbox as _bb, body_sdf as _bsdf, sdf_sample as _ss
            lo2, hi2 = _bb(body, n_uv=12)
            span2 = hi2 - lo2
            diag2 = float(np.linalg.norm(span2))

            if density_kind == "linear_z":
                _rho0 = kwargs.get("rho_0", 1.0)
                _alpha = kwargs.get("alpha", 1.0)
                _z_lo = float(lo2[2])
                _L = float(span2[2]) if float(span2[2]) > 1e-14 else 1.0
                def _df(p):
                    return float(_rho0 * (1.0 + _alpha * (p[2] - _z_lo) / _L))
            elif density_kind == "shell_dense":
                _sdf_g = _bsdf(body, resolution=32, padding=0.05)
                _t = kwargs.get("shell_thickness", 0.10 * diag2)
                _rs = kwargs.get("rho_shell", 2.0)
                _rc = kwargs.get("rho_core", 0.5)
                def _df(p):
                    d = _ss(_sdf_g, p)
                    return float(_rs) if d >= -_t else float(_rc)
            else:  # radial
                _geo_c = (lo2 + hi2) / 2.0
                _R_val = kwargs.get("R", 0.5 * diag2 / 2.0)
                _rho_max = kwargs.get("rho_max", 1.0)
                def _df(p):
                    return float(_rho_max / (1.0 + float(np.linalg.norm(p - _geo_c)) / max(_R_val, 1e-14)) ** 2)

            rng3 = np.random.default_rng(seed)
            ir2 = compute_inertia_density_field(body, _df, n_samples=n_samples * 5, rng=rng3)
            payload["inertia_tensor"] = ir2.inertia_tensor.tolist()
            payload["inertia_samples_used"] = ir2.samples_used
        except Exception as exc:
            payload["inertia_error"] = str(exc)

    return ok_payload(payload)
