"""
kerf-cad-core: sheet metal tools — T-1 (flange), T-2 (unfold), T-3 (flat-pattern DXF).

T-1: sheet_metal_flange
    Append a `sheet_metal_flange` feature node to a .feature file.
    Produces a folded B-rep: a base plate with a flange bent along a
    chosen edge at a specified bend radius, angle and wall thickness.

T-2: sheet_metal_unfold
    Compute the developed (flat) length of a flanged part using the
    neutral-axis bend-allowance formula:
        BA = angle_rad × (bend_radius + k_factor × thickness)
    Returns developed dimensions + bend-line table.  Pure-Python; no DB
    write — all input is taken from the existing flange node fields.

T-3: sheet_metal_flat_pattern
    Emit a 2D flat-pattern as a self-contained minimal DXF R12 string.
    Outline is a closed POLYLINE on layer "0"; bend lines are LINE
    entities on layer "BEND".  No external DXF library required
    (kerf-cad-core does not depend on kerf-imports; the tiny R12 writer
    is implemented inline here — about 25 lines, identical group-code
    format to kerf_imports.tools.draft._export_dxf).

Geometry contract (T-1, implemented in opSheetFlange in occtWorker.js):
    1. Base plate — box of (base_width × base_depth × thickness) at Z=0.
    2. Outer bend cylinder — quarter-cylinder (or partial) of radius
       (bend_radius + thickness) centred at the top edge being bent,
       oriented along the edge direction.  Trimmed to bend_angle.
    3. Flange wall — extruded rectangle from the far side of the bend arc,
       length `flange_length`, in the direction dictated by bend_angle.
    4. The three bodies are fused into one solid.

K-factor is stored on the node for T-2 to consume; it does not change the
folded shape but determines the neutral-axis position.

Validation (shared across T-1/T-2/T-3):
    k_factor   in (0, 1)          — strictly between 0 and 1
    bend_angle in (0, 180]        — degrees; 90° is most common
    edge_ref   non-empty string   — identifies which edge to fold along
    flange_length > 0
    thickness     > 0
    bend_radius   > 0
    base_width    > 0
    base_depth    > 0

Deferred (T-4):
    - Bend table / material allowance lookup from DB
    - Multi-flange (successive bend ops share the same sheet body)
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx


# ---------------------------------------------------------------------------
# Helpers (shared with surfacing.py pattern)
# ---------------------------------------------------------------------------

def _read_feature_content(ctx: ProjectCtx, file_id: uuid.UUID) -> tuple[str, Optional[str]]:
    try:
        row = ctx.pool.fetchone(
            "select content, kind from files where id = $1 and project_id = $2 and deleted_at is null",
            file_id, ctx.project_id,
        )
        if not row:
            return "", "NOT_FOUND"
        content, kind = row[0], row[1]
        if kind != "feature":
            return "", "NOT_FOUND"
        return content, None
    except Exception as e:
        return "", str(e)


def _next_node_id(content: str, op: str) -> str:
    if not content or not content.strip():
        return f"{op}-1"
    try:
        doc = json.loads(content)
    except Exception:
        return f"{op}-1"
    arr = doc.get("features", [])
    max_n = 0
    prefix = f"{op}-"
    for item in arr:
        if not isinstance(item, dict):
            continue
        nid = item.get("id", "")
        if nid.startswith(prefix):
            try:
                n = int(nid[len(prefix):])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f"{op}-{max_n + 1}"


def _append_feature_node(
    ctx: ProjectCtx, file_id: uuid.UUID, node: dict
) -> tuple[str, str, Optional[str]]:
    content, err = _read_feature_content(ctx, file_id)
    if err:
        return "", "", err

    doc: dict = {}
    if content and content.strip():
        try:
            doc = json.loads(content)
        except Exception:
            doc = {"version": 1, "features": []}
    else:
        doc = {"version": 1, "features": []}

    doc.setdefault("version", 1)
    if not isinstance(doc.get("features"), list):
        doc["features"] = []

    doc["features"].append(node)

    try:
        body = json.dumps(doc, indent=2)
    except Exception as e:
        return "", "", f"encode: {e}"

    try:
        ctx.pool.execute(
            "update files set content = $1, updated_at = now() where id = $2 and project_id = $3",
            body, file_id, ctx.project_id,
        )
    except Exception as e:
        return "", "", str(e)

    return "", node.get("id", ""), None


# ---------------------------------------------------------------------------
# Validation helper (importable by tests)
# ---------------------------------------------------------------------------

def validate_flange_args(
    edge_ref: str,
    flange_length: float,
    bend_angle_deg: float,
    bend_radius: float,
    thickness: float,
    k_factor: float,
    base_width: float,
    base_depth: float,
) -> tuple[Optional[str], Optional[str]]:
    """Return (error_message, error_code) or (None, None) on success."""
    if not edge_ref or not edge_ref.strip():
        return "edge_ref is required", "BAD_ARGS"
    if flange_length <= 0:
        return f"flange_length must be > 0; got {flange_length}", "BAD_ARGS"
    if bend_angle_deg <= 0 or bend_angle_deg > 180:
        return f"bend_angle_deg must be in (0, 180]; got {bend_angle_deg}", "BAD_ARGS"
    if bend_radius <= 0:
        return f"bend_radius must be > 0; got {bend_radius}", "BAD_ARGS"
    if thickness <= 0:
        return f"thickness must be > 0; got {thickness}", "BAD_ARGS"
    if k_factor <= 0 or k_factor >= 1:
        return f"k_factor must be in (0, 1); got {k_factor}", "BAD_ARGS"
    if base_width <= 0:
        return f"base_width must be > 0; got {base_width}", "BAD_ARGS"
    if base_depth <= 0:
        return f"base_depth must be > 0; got {base_depth}", "BAD_ARGS"
    return None, None


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

sheet_metal_flange_spec = ToolSpec(
    name="sheet_metal_flange",
    description=(
        "Append a `sheet_metal_flange` node to a `.feature` file. "
        "Creates a sheet-metal base plate with one folded flange along a specified "
        "edge. The result is a single folded solid B-rep at the given bend angle; "
        "flat-pattern / unfold is produced by the follow-up `sheet_metal_unfold` "
        "tool (T-2). "
        "Parameters: base_width × base_depth × thickness define the blank plate; "
        "edge_ref selects which edge to bend; flange_length is the straight wall "
        "after the arc; bend_angle_deg controls how far the flange rotates (90° = "
        "right-angle bend); bend_radius is the inside radius of the bend arc; "
        "k_factor (0 < k < 1) is the neutral-axis offset fraction used when "
        "computing developed length during unfold (stored on the node for T-2). "
        "Typical k-factor: 0.33 for hard materials, 0.44 for soft (default 0.44). "
        "Deferred (T-2/T-3/T-4): unfold, flat-pattern DXF, bend table."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Target .feature file id (UUID).",
            },
            "edge_ref": {
                "type": "string",
                "description": (
                    "Edge identifier along which the flange is bent. "
                    "Use a positional face-edge string such as 'edge-0' (top face, "
                    "first edge) or a named edge from the inspector. "
                    "For a freshly created pad/box the convention is: "
                    "'top-front', 'top-back', 'top-left', 'top-right'. "
                    "The worker maps these to the corresponding edge of the base plate."
                ),
            },
            "flange_length": {
                "type": "number",
                "description": "Length of the straight wall after the bend arc (mm). Must be > 0.",
            },
            "bend_angle_deg": {
                "type": "number",
                "description": (
                    "Bend angle in degrees — how far the flange rotates away from "
                    "the base plane. 90° = right-angle (most common); "
                    "range (0, 180]. Values < 90 produce acute flanges; "
                    "> 90 produce obtuse (return) flanges."
                ),
            },
            "bend_radius": {
                "type": "number",
                "description": "Inside radius of the bend arc (mm). Must be > 0.",
            },
            "thickness": {
                "type": "number",
                "description": "Sheet metal wall thickness (mm). Must be > 0.",
            },
            "k_factor": {
                "type": "number",
                "description": (
                    "Neutral-axis offset fraction, strictly in (0, 1). "
                    "Determines the developed length during unfold (T-2). "
                    "Does NOT change the folded shape. "
                    "Typical values: 0.33 (hard / tool steel), 0.44 (mild steel, default), "
                    "0.50 (aluminium), 0.38 (stainless steel)."
                ),
            },
            "base_width": {
                "type": "number",
                "description": "Width (X) of the base plate (mm). Must be > 0.",
            },
            "base_depth": {
                "type": "number",
                "description": "Depth (Y) of the base plate (mm). Must be > 0.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id (auto-generated if omitted).",
            },
        },
        "required": [
            "file_id", "edge_ref", "flange_length",
            "bend_angle_deg", "bend_radius", "thickness",
            "base_width", "base_depth",
        ],
    },
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@register(sheet_metal_flange_spec, write=True)
async def run_sheet_metal_flange(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id_str   = a.get("file_id", "").strip()
    edge_ref      = a.get("edge_ref", "").strip()
    flange_length = a.get("flange_length", 0)
    bend_angle    = a.get("bend_angle_deg", 90.0)
    bend_radius   = a.get("bend_radius", 1.0)
    thickness     = a.get("thickness", 1.0)
    k_factor      = a.get("k_factor", 0.44)
    base_width    = a.get("base_width", 50.0)
    base_depth    = a.get("base_depth", 50.0)
    node_id       = a.get("id", "").strip()

    if not file_id_str:
        return err_payload("file_id is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_str)
    except Exception:
        return err_payload("file_id must be a UUID", "BAD_ARGS")

    # --- Validation ---
    err_msg, err_code = validate_flange_args(
        edge_ref,
        float(flange_length),
        float(bend_angle),
        float(bend_radius),
        float(thickness),
        float(k_factor),
        float(base_width),
        float(base_depth),
    )
    if err_msg:
        return err_payload(err_msg, err_code)

    content, err = _read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = _next_node_id(content, "sheet_metal_flange")

    node: dict = {
        "id": node_id,
        "op": "sheet_metal_flange",
        "edge_ref": edge_ref,
        "flange_length": float(flange_length),
        "bend_angle_deg": float(bend_angle),
        "bend_radius": float(bend_radius),
        "thickness": float(thickness),
        "k_factor": float(k_factor),
        "base_width": float(base_width),
        "base_depth": float(base_depth),
    }

    _name, nid, ferr = _append_feature_node(ctx, fid, node)
    if ferr:
        return err_payload(ferr, "ERROR")

    return ok_payload({
        "file_id": file_id_str,
        "id": nid,
        "op": "sheet_metal_flange",
        "edge_ref": edge_ref,
        "flange_length": float(flange_length),
        "bend_angle_deg": float(bend_angle),
        "bend_radius": float(bend_radius),
        "thickness": float(thickness),
        "k_factor": float(k_factor),
        "note": (
            "Folded B-rep produced. "
            "Unfold / flat-pattern: use sheet_metal_unfold (T-2)."
        ),
    })


# ===========================================================================
# T-2: Unfold solver
# ===========================================================================

def compute_unfold(
    base_length: float,
    flange_length: float,
    bend_angle_deg: float,
    bend_radius: float,
    thickness: float,
    k_factor: float,
) -> dict:
    """
    Compute the developed (flat) length and bend-line positions for a single
    base+bend+flange part.

    Neutral-axis bend-allowance formula:
        BA = angle_rad × (bend_radius + k_factor × thickness)

    Parameters
    ----------
    base_length:
        Length of the base plate in the bend direction (mm). For a
        ``sheet_metal_flange`` node this is ``base_depth`` when bending
        along a front/back edge, or ``base_width`` along a left/right edge.
        The caller is responsible for choosing the appropriate dimension.
    flange_length:
        Straight-wall length after the bend arc (mm).
    bend_angle_deg:
        Bend angle in degrees, in (0, 180].
    bend_radius:
        Inside bend radius (mm).
    thickness:
        Sheet thickness (mm).
    k_factor:
        Neutral-axis offset fraction, in (0, 1).

    Returns
    -------
    dict with keys:
        ``bend_allowance``   — BA in mm (float)
        ``developed_length`` — base_length + BA + flange_length (float)
        ``bend_lines``       — list of two dicts, each with ``position``
                               (distance from one end, mm) and ``label``
                               ("bend-start" / "bend-end")
    """
    angle_rad = math.radians(bend_angle_deg)
    ba = angle_rad * (bend_radius + k_factor * thickness)
    developed = base_length + ba + flange_length
    return {
        "bend_allowance": round(ba, 6),
        "developed_length": round(developed, 6),
        "bend_lines": [
            {"position": round(base_length, 6), "label": "bend-start"},
            {"position": round(base_length + ba, 6), "label": "bend-end"},
        ],
    }


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

sheet_metal_unfold_spec = ToolSpec(
    name="sheet_metal_unfold",
    description=(
        "Compute the developed (flat) length of a sheet-metal part produced "
        "by `sheet_metal_flange`.  Uses the neutral-axis bend-allowance formula: "
        "BA = angle_rad × (bend_radius + k_factor × thickness). "
        "Returns: bend_allowance (mm), developed_length (mm), and bend_lines "
        "(positions of bend-start / bend-end from the base end). "
        "All geometry inputs are taken directly from the `sheet_metal_flange` "
        "node — pass the same k_factor / bend_radius / bend_angle_deg / "
        "thickness / flange_length values.  The `base_length` parameter "
        "selects which base dimension feeds into the unfold (base_depth for "
        "front/back bends, base_width for left/right bends). "
        "Does NOT write to any file; purely computes developed geometry. "
        "Flat-pattern DXF: use sheet_metal_flat_pattern (T-3). "
        "Bend-table / material lookup: deferred (T-4)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "base_length": {
                "type": "number",
                "description": (
                    "Base plate dimension in the bend direction (mm). "
                    "Use base_depth for top-front / top-back bends; "
                    "use base_width for top-left / top-right bends."
                ),
            },
            "flange_length": {
                "type": "number",
                "description": "Straight-wall length after the bend arc (mm).",
            },
            "bend_angle_deg": {
                "type": "number",
                "description": "Bend angle in degrees, in (0, 180]. Matches the flange node.",
            },
            "bend_radius": {
                "type": "number",
                "description": "Inside bend radius (mm). Matches the flange node.",
            },
            "thickness": {
                "type": "number",
                "description": "Sheet thickness (mm). Matches the flange node.",
            },
            "k_factor": {
                "type": "number",
                "description": (
                    "Neutral-axis offset fraction, in (0, 1). "
                    "Matches the k_factor stored on the flange node. "
                    "Default 0.44 (mild steel)."
                ),
            },
        },
        "required": [
            "base_length", "flange_length", "bend_angle_deg",
            "bend_radius", "thickness",
        ],
    },
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@register(sheet_metal_unfold_spec, write=False)
async def run_sheet_metal_unfold(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    base_length   = a.get("base_length", 0)
    flange_length = a.get("flange_length", 0)
    bend_angle    = a.get("bend_angle_deg", 90.0)
    bend_radius   = a.get("bend_radius", 1.0)
    thickness     = a.get("thickness", 1.0)
    k_factor      = a.get("k_factor", 0.44)

    try:
        base_length   = float(base_length)
        flange_length = float(flange_length)
        bend_angle    = float(bend_angle)
        bend_radius   = float(bend_radius)
        thickness     = float(thickness)
        k_factor      = float(k_factor)
    except (TypeError, ValueError) as e:
        return err_payload(f"numeric argument required: {e}", "BAD_ARGS")

    if base_length <= 0:
        return err_payload(f"base_length must be > 0; got {base_length}", "BAD_ARGS")
    if flange_length <= 0:
        return err_payload(f"flange_length must be > 0; got {flange_length}", "BAD_ARGS")
    if bend_angle <= 0 or bend_angle > 180:
        return err_payload(f"bend_angle_deg must be in (0, 180]; got {bend_angle}", "BAD_ARGS")
    if bend_radius <= 0:
        return err_payload(f"bend_radius must be > 0; got {bend_radius}", "BAD_ARGS")
    if thickness <= 0:
        return err_payload(f"thickness must be > 0; got {thickness}", "BAD_ARGS")
    if k_factor <= 0 or k_factor >= 1:
        return err_payload(f"k_factor must be in (0, 1); got {k_factor}", "BAD_ARGS")

    result = compute_unfold(
        base_length=base_length,
        flange_length=flange_length,
        bend_angle_deg=bend_angle,
        bend_radius=bend_radius,
        thickness=thickness,
        k_factor=k_factor,
    )
    return ok_payload(result)


# ===========================================================================
# T-3: Flat-pattern DXF
# ===========================================================================

def _flat_pattern_dxf_r12(
    width: float,
    developed_length: float,
    bend_line_positions: list[float],
) -> str:
    """
    Emit a minimal DXF R12 string for a flat-pattern.

    Layout (X = along developed length, Y = width):
        - Closed POLYLINE outline on layer "0" (the outer rectangle).
        - One LINE per bend-line position, spanning Y=0..width, on layer "BEND".

    Note: kerf-imports contains a .draft→DXF-R12 writer
    (kerf_imports.tools.draft._export_dxf) but kerf-cad-core does not
    depend on kerf-imports.  Rather than add a cross-package dependency
    this function emits an equivalent R12 string directly using DXF
    group-code pairs — the format is trivial and self-contained.
    """
    lines: list[str] = []

    def gc(*pairs):
        """Append group-code / value pairs."""
        for code, val in zip(pairs[::2], pairs[1::2]):
            lines.append(str(code))
            if isinstance(val, float):
                lines.append(f"{val:.6f}")
            else:
                lines.append(str(val))

    # --- Header ---
    gc(0, "SECTION", 2, "HEADER")
    gc(9, "$ACADVER", 1, "AC1009")
    gc(0, "ENDSEC")

    # --- Entities ---
    gc(0, "SECTION", 2, "ENTITIES")

    # Outline: closed polyline rectangle (4 vertices, CCW)
    # Bottom-left → bottom-right → top-right → top-left
    outline = [
        (0.0,       0.0),
        (developed_length, 0.0),
        (developed_length, width),
        (0.0,       width),
    ]
    gc(0, "POLYLINE", 8, "0", 66, 1, 70, 1)  # 70=1: closed
    for vx, vy in outline:
        gc(0, "VERTEX", 8, "0", 10, vx, 20, vy, 30, 0.0)
    gc(0, "SEQEND", 8, "0")

    # Bend lines on layer BEND
    for pos in bend_line_positions:
        gc(0, "LINE", 8, "BEND", 10, pos, 20, 0.0, 30, 0.0, 11, pos, 21, width, 31, 0.0)

    gc(0, "ENDSEC")
    gc(0, "EOF")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

sheet_metal_flat_pattern_spec = ToolSpec(
    name="sheet_metal_flat_pattern",
    description=(
        "Produce a 2D flat-pattern DXF R12 string for a sheet-metal part "
        "described by `sheet_metal_flange` parameters. "
        "Internally runs the T-2 unfold solver (same BA formula as "
        "`sheet_metal_unfold`) then emits a self-contained DXF R12 file "
        "string with: a closed POLYLINE outline on layer '0', and LINE "
        "entities for each bend line on layer 'BEND'. "
        "Returns the DXF text and the computed unfold dimensions. "
        "The caller can write the DXF string to a .dxf file or pass it to "
        "the DXF import route. "
        "No DB write; purely computes and returns the DXF string. "
        "Deferred (T-4): bend-table / material allowance lookup."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "base_length": {
                "type": "number",
                "description": (
                    "Base plate dimension in the bend direction (mm). "
                    "Use base_depth for top-front / top-back bends; "
                    "use base_width for top-left / top-right bends."
                ),
            },
            "width": {
                "type": "number",
                "description": (
                    "Width of the flat pattern perpendicular to the bend "
                    "direction (mm). Use base_width for front/back bends; "
                    "use base_depth for left/right bends."
                ),
            },
            "flange_length": {
                "type": "number",
                "description": "Straight-wall length after the bend arc (mm).",
            },
            "bend_angle_deg": {
                "type": "number",
                "description": "Bend angle in degrees, in (0, 180]. Matches the flange node.",
            },
            "bend_radius": {
                "type": "number",
                "description": "Inside bend radius (mm). Matches the flange node.",
            },
            "thickness": {
                "type": "number",
                "description": "Sheet thickness (mm). Matches the flange node.",
            },
            "k_factor": {
                "type": "number",
                "description": (
                    "Neutral-axis offset fraction, in (0, 1). "
                    "Default 0.44 (mild steel)."
                ),
            },
        },
        "required": [
            "base_length", "width", "flange_length",
            "bend_angle_deg", "bend_radius", "thickness",
        ],
    },
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@register(sheet_metal_flat_pattern_spec, write=False)
async def run_sheet_metal_flat_pattern(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    base_length   = a.get("base_length", 0)
    width         = a.get("width", 0)
    flange_length = a.get("flange_length", 0)
    bend_angle    = a.get("bend_angle_deg", 90.0)
    bend_radius   = a.get("bend_radius", 1.0)
    thickness     = a.get("thickness", 1.0)
    k_factor      = a.get("k_factor", 0.44)

    try:
        base_length   = float(base_length)
        width         = float(width)
        flange_length = float(flange_length)
        bend_angle    = float(bend_angle)
        bend_radius   = float(bend_radius)
        thickness     = float(thickness)
        k_factor      = float(k_factor)
    except (TypeError, ValueError) as e:
        return err_payload(f"numeric argument required: {e}", "BAD_ARGS")

    if base_length <= 0:
        return err_payload(f"base_length must be > 0; got {base_length}", "BAD_ARGS")
    if width <= 0:
        return err_payload(f"width must be > 0; got {width}", "BAD_ARGS")
    if flange_length <= 0:
        return err_payload(f"flange_length must be > 0; got {flange_length}", "BAD_ARGS")
    if bend_angle <= 0 or bend_angle > 180:
        return err_payload(f"bend_angle_deg must be in (0, 180]; got {bend_angle}", "BAD_ARGS")
    if bend_radius <= 0:
        return err_payload(f"bend_radius must be > 0; got {bend_radius}", "BAD_ARGS")
    if thickness <= 0:
        return err_payload(f"thickness must be > 0; got {thickness}", "BAD_ARGS")
    if k_factor <= 0 or k_factor >= 1:
        return err_payload(f"k_factor must be in (0, 1); got {k_factor}", "BAD_ARGS")

    unfold = compute_unfold(
        base_length=base_length,
        flange_length=flange_length,
        bend_angle_deg=bend_angle,
        bend_radius=bend_radius,
        thickness=thickness,
        k_factor=k_factor,
    )

    bend_positions = [bl["position"] for bl in unfold["bend_lines"]]
    dxf_string = _flat_pattern_dxf_r12(
        width=width,
        developed_length=unfold["developed_length"],
        bend_line_positions=bend_positions,
    )

    return ok_payload({
        "dxf": dxf_string,
        "developed_length": unfold["developed_length"],
        "bend_allowance": unfold["bend_allowance"],
        "bend_lines": unfold["bend_lines"],
        "width": width,
        "dxf_note": (
            "Self-contained DXF R12. Outline on layer '0'; "
            "bend lines on layer 'BEND'. "
            "kerf-imports DXF writer not used (no cross-package dep)."
        ),
    })
