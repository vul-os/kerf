"""
LLM tool: export_odbpp

Generates an ODB++ fab archive from a CircuitJSON board.  ODB++ is a
Mentor/Valor directory-tree format (ISO/IEC 13052) widely accepted by
leading PCB fabs (Sanmina, TTM, Jabil, etc.) alongside IPC-2581 as one of
the two main "intelligent fab" delivery formats.

The archive is a .tgz (gzip-compressed tar) with the layout:
  <stem>/misc/info
  <stem>/steps/pcb/stephdr
  <stem>/steps/pcb/layers/<layer>/attrlist
  <stem>/steps/pcb/layers/<layer>/components
  <stem>/steps/pcb/layers/<layer>/features

for layers: top_copper, bottom_copper, top_silk, bottom_silk,
            top_mask, bottom_mask, drill, outline.

The .tgz bytes are returned base64-encoded so the LLM can offer the user a
download link.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

from kerf_electronics.fab.odbpp.writer import export_odbpp as _export_odbpp


# ─── tool spec ────────────────────────────────────────────────────────────────

export_odbpp_spec = ToolSpec(
    name="export_odbpp",
    description=(
        "Export a CircuitJSON board as an ODB++ fab archive (.tgz). "
        "ODB++ is a Mentor/Valor directory-tree format (ISO/IEC 13052) widely "
        "accepted by leading PCB fabs alongside IPC-2581 as an 'intelligent fab' "
        "delivery format. "
        "The archive contains: misc/info (EDA tool metadata), "
        "steps/pcb/stephdr (board header), and per-layer attrlist + components + "
        "features files for all standard layers "
        "(top_copper, bottom_copper, top/bottom silk, top/bottom mask, drill, outline). "
        "Returns tgz_b64 (base64 .tgz bytes), manifest (list of paths in the archive), "
        "and a download filename. "
        "Use this when the user asks to export ODB++, or to send the board to a "
        "Sanmina/TTM/Jabil fab that requires ODB++ format."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "type": "array",
                "description": "Parsed CircuitJSON array from the board file.",
                "items": {"type": "object"},
            },
            "stem": {
                "type": "string",
                "description": (
                    "Base name used as the top-level ODB++ directory and step name "
                    "(no extension). Default 'board'."
                ),
            },
        },
        "required": ["circuit_json"],
    },
)


# ─── tool handler ─────────────────────────────────────────────────────────────

@register(export_odbpp_spec)
async def run_export_odbpp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    if not isinstance(circuit_json, list):
        return err_payload("circuit_json must be an array", "BAD_ARGS")

    stem = a.get("stem", "board") or "board"

    try:
        result = _export_odbpp(circuit_json, stem=stem)
    except Exception as e:
        return err_payload(f"ODB++ export failed: {e}", "EXPORT_ERROR")

    tgz_bytes: bytes = result["tgz_bytes"]
    manifest: list[str] = result["manifest"]
    tgz_b64 = base64.b64encode(tgz_bytes).decode()
    tgz_filename = f"{stem}-odbpp.tgz"

    return ok_payload({
        "tgz_filename": tgz_filename,
        "tgz_b64": tgz_b64,
        "tgz_size_bytes": len(tgz_bytes),
        "manifest": manifest,
        "layer_count": sum(1 for p in manifest if "/features" in p),
        "message": (
            f"ODB++ archive ready: {tgz_filename} ({len(tgz_bytes):,} bytes). "
            f"Contains {len(manifest)} files across "
            f"{sum(1 for p in manifest if '/features' in p)} layer(s). "
            "Decode tgz_b64 to obtain the .tgz archive for upload to your fab."
        ),
    })


# ─── TOOLS export (consumed by plugin._register_tools) ───────────────────────

TOOLS = [
    (export_odbpp_spec.name, export_odbpp_spec, run_export_odbpp),
]
