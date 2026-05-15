"""
kerf_cad_core.nesting.tools — LLM tool wrappers for 2-D part nesting.

Registers two tools:

  nest_parts
      Pack a list of rectangular parts onto stock sheets.
      Returns placement list, sheet count, utilisation %, cut-length estimate.

  nest_report
      Format a human-readable nesting summary from nest_parts output.

Both tools are pure-Python and never raise; errors are returned as
{ok: false, errors: [...]}.

Author: imranparuk
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.nesting.pack import nest_parts as _nest_parts, result_to_dict


# ---------------------------------------------------------------------------
# T-1: nest_parts
# ---------------------------------------------------------------------------

_nest_parts_spec = ToolSpec(
    name="nest_parts",
    description=(
        "Nest a list of rectangular parts onto stock sheets using a skyline "
        "bin-packing algorithm with optional 90° rotation. "
        "\n"
        "Inputs: an array of part objects (name, w, h, optional qty), "
        "sheet dimensions (sheet_w × sheet_h), kerf gap, border margin, "
        "and allow_rotate flag. "
        "\n"
        "Algorithm: deterministic skyline (bottom-left, best-fit segment). "
        "Rotation 0° tried first; 90° tried when allow_rotate=true and the "
        "rotated footprint is different. "
        "Parts that exceed the usable sheet area (sheet − 2×margin) trigger a "
        "friendly error — they are never silently dropped. "
        "\n"
        "Returns: {ok, sheets:[{sheet, placements:[{part, x, y, w, h, rot}]}], "
        "sheets_used, utilization, cut_length, errors:[]}. "
        "utilization is total part area / (sheets_used × sheet area), in (0, 1]. "
        "cut_length is the estimated total laser path (sum of part perimeters, mm). "
        "\n"
        "Units: same as input (mm recommended). "
        "Never raises; all errors returned in errors[]."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "parts": {
                "type": "array",
                "description": (
                    "Parts to nest. Each item: "
                    "{name (str), w (float, mm), h (float, mm), qty (int, default 1)}. "
                    "w and h are bounding-box dimensions."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Part identifier."},
                        "w": {"type": "number", "description": "Bounding-box width (mm). Must be > 0."},
                        "h": {"type": "number", "description": "Bounding-box height (mm). Must be > 0."},
                        "qty": {"type": "integer", "description": "Repeat count (default 1)."},
                    },
                    "required": ["name", "w", "h"],
                },
            },
            "sheet_w": {
                "type": "number",
                "description": "Stock sheet width (mm). Must be > 0.",
            },
            "sheet_h": {
                "type": "number",
                "description": "Stock sheet height (mm). Must be > 0.",
            },
            "kerf": {
                "type": "number",
                "description": (
                    "Kerf / cutter gap between adjacent parts (mm). "
                    "Also applied between parts and the margin border. "
                    "Default 0. Typical laser: 0.1–0.5 mm."
                ),
            },
            "margin": {
                "type": "number",
                "description": (
                    "Border margin inset on all four edges of each sheet (mm). "
                    "Default 0. Typical value: 5–10 mm."
                ),
            },
            "allow_rotate": {
                "type": "boolean",
                "description": (
                    "Allow parts to be rotated 90°. "
                    "Default true. Disable for parts with a fixed grain direction."
                ),
            },
        },
        "required": ["parts", "sheet_w", "sheet_h"],
    },
)


@register(_nest_parts_spec, write=False)
async def run_nest_parts(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    parts = a.get("parts")
    if not isinstance(parts, list):
        return err_payload("parts must be a list", "BAD_ARGS")

    try:
        sheet_w = float(a.get("sheet_w", 0))
        sheet_h = float(a.get("sheet_h", 0))
        kerf    = float(a.get("kerf", 0.0))
        margin  = float(a.get("margin", 0.0))
    except (TypeError, ValueError) as exc:
        return err_payload(f"numeric argument required: {exc}", "BAD_ARGS")

    allow_rotate = bool(a.get("allow_rotate", True))

    result = _nest_parts(
        parts=parts,
        sheet_w=sheet_w,
        sheet_h=sheet_h,
        kerf=kerf,
        margin=margin,
        allow_rotate=allow_rotate,
    )

    payload = result_to_dict(result)
    if result.ok:
        payload["utilization_pct"] = round(result.utilization * 100, 2)
    return ok_payload(payload)


# ---------------------------------------------------------------------------
# T-2: nest_report
# ---------------------------------------------------------------------------

_nest_report_spec = ToolSpec(
    name="nest_report",
    description=(
        "Format a human-readable nesting report from nest_parts output. "
        "\n"
        "Input: the output dict from nest_parts (ok, sheets, sheets_used, "
        "utilization, cut_length). "
        "Optional: sheet_w, sheet_h (mm) for area context; "
        "material (string) and kerf (mm) for header context. "
        "\n"
        "Output: {ok, report_text, summary_lines}. "
        "report_text is a formatted multi-line string. "
        "summary_lines is the same content as a list of strings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nesting": {
                "type": "object",
                "description": "Output dict from nest_parts.",
            },
            "sheet_w": {
                "type": "number",
                "description": "Sheet width (mm) — used for context in the report header.",
            },
            "sheet_h": {
                "type": "number",
                "description": "Sheet height (mm) — used for context in the report header.",
            },
            "material": {
                "type": "string",
                "description": "Optional material name for the report header.",
            },
            "kerf": {
                "type": "number",
                "description": "Kerf gap used (mm) — displayed in the report header.",
            },
        },
        "required": ["nesting"],
    },
)


@register(_nest_report_spec, write=False)
async def run_nest_report(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    nesting = a.get("nesting")
    if not isinstance(nesting, dict):
        return err_payload("nesting must be the output dict from nest_parts", "BAD_ARGS")

    sheet_w  = a.get("sheet_w")
    sheet_h  = a.get("sheet_h")
    material = str(a.get("material", "—"))
    kerf     = a.get("kerf")

    try:
        ok            = bool(nesting.get("ok", False))
        sheets_used   = int(nesting.get("sheets_used", 0))
        utilization   = float(nesting.get("utilization", 0.0))
        cut_length    = float(nesting.get("cut_length", 0.0))
        nest_errors   = nesting.get("errors", [])
        sheets        = nesting.get("sheets", [])
    except (TypeError, ValueError) as exc:
        return err_payload(f"nesting field parse error: {exc}", "BAD_ARGS")

    lines: list[str] = ["=" * 56, "  NESTING / CUT-OPTIMISATION REPORT"]

    if sheet_w is not None and sheet_h is not None:
        lines.append(f"  Sheet        : {sheet_w} × {sheet_h} mm")
    if material and material != "—":
        lines.append(f"  Material     : {material}")
    if kerf is not None:
        lines.append(f"  Kerf gap     : {kerf} mm")
    lines.append("=" * 56)

    if not ok:
        lines.append("  STATUS: FAILED")
        for e in nest_errors:
            lines.append(f"  Error: {e}")
        lines.append("=" * 56)
        return ok_payload({
            "ok": True,
            "report_text": "\n".join(lines),
            "summary_lines": lines,
        })

    lines += [
        f"  Sheets used  : {sheets_used}",
        f"  Utilisation  : {utilization * 100:.1f}%",
        f"  Cut length   : {cut_length:.1f} mm",
        "-" * 56,
    ]

    total_parts = sum(len(s.get("placements", [])) for s in sheets)
    lines.append(f"  Total parts  : {total_parts}")
    lines.append("-" * 56)

    for s in sheets:
        idx  = s.get("sheet", "?")
        pls  = s.get("placements", [])
        lines.append(f"  Sheet {idx}:  {len(pls)} part(s)")
        for p in pls:
            rot_str = f" [rot {p['rot']}°]" if p.get("rot") else ""
            lines.append(
                f"    {p['part']}  {p['w']}×{p['h']} mm"
                f"  @ ({p['x']:.2f}, {p['y']:.2f}){rot_str}"
            )

    lines.append("=" * 56)
    return ok_payload({
        "ok": True,
        "report_text": "\n".join(lines),
        "summary_lines": lines,
    })
