import json
import uuid

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


fem_run_spec = ToolSpec(
    name="fem_run",
    description="Run a finite-element stress analysis on a STEP file. Returns max von-Mises stress, displacement, FoS, and modal frequencies.",
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "material_props": {
                "type": "object",
                "properties": {
                    "E": {"type": "number"},
                    "nu": {"type": "number"},
                    "rho": {"type": "number"},
                    "yield_strength": {"type": "number"},
                },
                "required": ["E", "nu", "rho", "yield_strength"],
            },
            "boundary_conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["fixed", "displacement"]},
                        "face_tags": {"type": "array", "items": {"type": "number"}},
                        "ux": {"type": "number"},
                        "uy": {"type": "number"},
                        "uz": {"type": "number"},
                    },
                    "required": ["type", "face_tags"],
                },
            },
            "loads": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["pressure", "force"]},
                        "face_tags": {"type": "array", "items": {"type": "number"}},
                        "value": {"type": "number"},
                    },
                    "required": ["type", "face_tags", "value"],
                },
            },
            "mesh_size": {"type": "number"},
            "solver": {"type": "string", "enum": ["fenicsx", "calculix"]},
            "analysis_type": {"type": "string", "enum": ["linear_static", "modal", "thermal"]},
        },
        "required": ["file_id", "material_props", "boundary_conditions", "loads"],
    },
)


@register(fem_run_spec, write=True)
async def run_fem_run(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id = a.get("file_id", "")
    material_props = a.get("material_props")
    boundary_conditions = a.get("boundary_conditions", [])
    loads = a.get("loads", [])

    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")
    if not material_props:
        return err_payload("material_props is required", "BAD_ARGS")
    if not boundary_conditions:
        return err_payload("at least one boundary_conditions entry is required", "BAD_ARGS")
    if not loads:
        return err_payload("at least one load entry is required", "BAD_ARGS")

    spec = {
        "material_props": material_props,
        "boundary_conditions": boundary_conditions,
        "loads": loads,
        "mesh_size": a.get("mesh_size", 0.01),
        "solver": a.get("solver", "fenicsx"),
        "analysis_type": a.get("analysis_type", "linear_static"),
    }
    spec_json = json.dumps(spec)

    row = await ctx.pool.fetchrow(
        """INSERT INTO fem_jobs (file_id, project_id, input_spec)
           VALUES ($1, $2, $3)
           ON CONFLICT (file_id) WHERE status IN ('queued', 'running')
           DO UPDATE SET input_spec = $3, status = 'queued', error = NULL,
               started_at = NULL, finished_at = NULL
           RETURNING id""",
        file_id, ctx.project_id, spec_json,
    )

    if not row:
        return err_payload("failed to enqueue FEM job", "ERROR")

    return ok_payload({
        "job_id": str(row["id"]),
        "status": "queued",
        "message": "FEM job enqueued. Poll fem_job_status(file_id) for results.",
    })


fem_job_status_spec = ToolSpec(
    name="fem_job_status",
    description="Poll the status of a FEM analysis job. Returns the job status, and when complete the result JSON.",
    input_schema={
        "type": "object",
        "properties": {"file_id": {"type": "string"}},
        "required": ["file_id"],
    },
)


@register(fem_job_status_spec)
async def run_fem_job_status(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id = a.get("file_id", "")
    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")

    row = await ctx.pool.fetchrow(
        """SELECT status, result_json, error FROM fem_jobs
           WHERE file_id = $1 AND project_id = $2
           ORDER BY created_at DESC LIMIT 1""",
        file_id, ctx.project_id,
    )

    if not row:
        return err_payload("fem job not found", "NOT_FOUND")

    resp = {"file_id": file_id, "status": row["status"]}
    if row["status"] == "done" and row["result_json"]:
        try:
            result = json.loads(row["result_json"])
            resp["result"] = result
        except Exception:
            pass
    elif row["status"] == "error" and row["error"]:
        resp["error"] = row["error"]

    return ok_payload(resp)


# ---------------------------------------------------------------------------
# fem_nonlinear_bar  — uniaxial J2 isotropic-hardening bar
# ---------------------------------------------------------------------------

fem_nonlinear_bar_spec = ToolSpec(
    name="fem_nonlinear_bar",
    description=(
        "Simulate a uniaxial bar under incremental loading using J2 "
        "isotropic-hardening plasticity (von Mises return mapping). "
        "Returns stress, strain, and plastic-strain history per load step. "
        "Useful for material-point / coupon-level nonlinear material verification."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "E": {
                "type": "number",
                "description": "Young's modulus [Pa]",
            },
            "sigma_y0": {
                "type": "number",
                "description": "Initial yield stress [Pa]",
            },
            "H": {
                "type": "number",
                "description": "Isotropic hardening modulus [Pa]. Use 0 for perfect plasticity.",
            },
            "load_steps": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Sequence of target values for each load step. "
                    "If force_controlled=false (default) these are total strain targets; "
                    "if force_controlled=true these are stress targets."
                ),
            },
            "force_controlled": {
                "type": "boolean",
                "description": "If true, load_steps are stress targets; otherwise strain targets.",
                "default": False,
            },
            "max_iter": {
                "type": "integer",
                "description": "Max Newton iterations per step (default 50).",
                "default": 50,
            },
            "tol": {
                "type": "number",
                "description": "Relative convergence tolerance (default 1e-10).",
                "default": 1e-10,
            },
        },
        "required": ["E", "sigma_y0", "H", "load_steps"],
    },
)


@register(fem_nonlinear_bar_spec)
async def run_fem_nonlinear_bar(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    E = a.get("E")
    sigma_y0 = a.get("sigma_y0")
    H = a.get("H")
    load_steps = a.get("load_steps")

    if E is None or sigma_y0 is None or H is None or load_steps is None:
        return err_payload("E, sigma_y0, H, load_steps are required", "BAD_ARGS")
    if not isinstance(load_steps, list):
        return err_payload("load_steps must be a list", "BAD_ARGS")

    from kerf_fem.nonlinear_bar import run_nonlinear_bar

    result = run_nonlinear_bar(
        E=float(E),
        sigma_y0=float(sigma_y0),
        H=float(H),
        load_steps=[float(v) for v in load_steps],
        force_controlled=bool(a.get("force_controlled", False)),
        max_iter=int(a.get("max_iter", 50)),
        tol=float(a.get("tol", 1e-10)),
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# fem_truss_plastic  — small-strain 2-D truss with per-element plasticity
# ---------------------------------------------------------------------------

fem_truss_plastic_spec = ToolSpec(
    name="fem_truss_plastic",
    description=(
        "Nonlinear quasi-static analysis of a 2-D pin-jointed truss with "
        "J2 isotropic-hardening plasticity per bar element. "
        "Incremental load stepping + Newton-Raphson global equilibrium. "
        "Returns per-step displacements, element stresses, and plastic strains."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "List of [x, y] node coordinates [m].",
            },
            "elements": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "List of [node_i, node_j] element connectivity (0-based).",
            },
            "E": {"type": "number", "description": "Young's modulus [Pa]"},
            "area": {"type": "number", "description": "Cross-sectional area [m²]"},
            "sigma_y0": {"type": "number", "description": "Initial yield stress [Pa]"},
            "H": {"type": "number", "description": "Isotropic hardening modulus [Pa]"},
            "load_steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "forces": {
                            "type": "object",
                            "description": "Map of node_index (string) → [Fx, Fy] [N]",
                        },
                        "fixed_dofs": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "DOF indices to fix (2*node for x, 2*node+1 for y).",
                        },
                    },
                },
                "description": "Sequence of load steps; BCs taken from first step.",
            },
            "max_iter": {"type": "integer", "default": 50},
            "tol": {"type": "number", "default": 1e-8},
        },
        "required": ["nodes", "elements", "E", "area", "sigma_y0", "H", "load_steps"],
    },
)


@register(fem_truss_plastic_spec)
async def run_fem_truss_plastic(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = ["nodes", "elements", "E", "area", "sigma_y0", "H", "load_steps"]
    for key in required:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    from kerf_fem.nonlinear_bar import run_truss_plastic

    result = run_truss_plastic(
        nodes=[tuple(n) for n in a["nodes"]],
        elements=[tuple(e) for e in a["elements"]],
        E=float(a["E"]),
        area=float(a["area"]),
        sigma_y0=float(a["sigma_y0"]),
        H=float(a["H"]),
        load_steps=a["load_steps"],
        max_iter=int(a.get("max_iter", 50)),
        tol=float(a.get("tol", 1e-8)),
    )
    return ok_payload(result)
