"""
multi_board/multi_board_tools.py — LLM tool wrappers for multi-board workspace.

Exposes five tools to the kerf LLM agent:

  electronics_mb3d_create_workspace
    Create a new multi-board workspace with initial board placements.

  electronics_mb3d_add_connector
    Declare a mating connector pair between two boards.

  electronics_mb3d_validate_workspace
    Run connector mating validation + board overlap checks.

  electronics_mb3d_net_map
    Compute the cross-board net map and flag floating nets / Z0 mismatches.

  electronics_mb3d_export_step
    Export the multi-board assembly as a STEP AP242 file (base64-encoded).

References
----------
Altium Designer Multi-Board Design User Manual:
  https://www.altium.com/documentation/altium-designer/multi-board-design
IPC-2581 Rev B §7.4 — multi-board net declaration.
IEEE 1149.1-2013 §6 — multi-board boundary-scan chain.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.multi_board.inter_board_nets import (
    check_signal_continuity,
    compute_workspace_net_map,
)
from kerf_electronics.multi_board.workspace import (
    BoardPlacement,
    InterBoardConnector,
    MultiBoardWorkspace,
)


# ---------------------------------------------------------------------------
# Tool 1: electronics_mb3d_create_workspace
# ---------------------------------------------------------------------------

_create_workspace_spec = ToolSpec(
    name="electronics_mb3d_create_workspace",
    description=(
        "Create an Altium MB3D-style multi-board workspace. "
        "Accepts a workspace name and a list of board placements (board_id, "
        "file_path, position [x,y,z mm], rotation_xyz_deg, optional "
        "board_width_mm/board_height_mm). "
        "Returns workspace summary JSON including all board IDs and a "
        "preliminary overlap check. "
        "References: Altium MB3D §2-3; IPC-2581 §7.4.1."
    ),
    input_schema={
        "type": "object",
        "required": ["workspace_name", "boards"],
        "properties": {
            "workspace_name": {
                "type": "string",
                "description": "Human-readable workspace name.",
            },
            "boards": {
                "type": "array",
                "description": "List of board placement descriptors.",
                "items": {
                    "type": "object",
                    "required": ["board_id", "file_path", "position"],
                    "properties": {
                        "board_id": {"type": "string"},
                        "file_path": {"type": "string"},
                        "position": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "rotation_xyz_deg": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "board_width_mm": {"type": "number"},
                        "board_height_mm": {"type": "number"},
                    },
                },
            },
            "enclosure_step_file": {
                "type": "string",
                "description": "Optional path to enclosure STEP model.",
            },
        },
    },
)


@register(_create_workspace_spec)
def _handle_create_workspace(args: dict[str, Any]) -> str:
    try:
        placements = []
        for b in args["boards"]:
            pos = tuple(float(v) for v in b["position"])  # type: ignore[arg-type]
            rot = tuple(float(v) for v in b.get("rotation_xyz_deg", [0.0, 0.0, 0.0]))  # type: ignore[arg-type]
            placements.append(
                BoardPlacement(
                    board_id=str(b["board_id"]),
                    file_path=str(b["file_path"]),
                    position=pos,  # type: ignore[arg-type]
                    rotation_xyz_deg=rot,  # type: ignore[arg-type]
                    board_width_mm=float(b.get("board_width_mm", 100.0)),
                    board_height_mm=float(b.get("board_height_mm", 80.0)),
                )
            )

        ws = MultiBoardWorkspace(
            workspace_name=str(args["workspace_name"]),
            boards=placements,
            connectors=[],
            enclosure_step_file=args.get("enclosure_step_file"),
        )

        overlap_warnings = ws.check_board_overlaps()

        return ok_payload(
            {
                "workspace_name": ws.workspace_name,
                "board_count": len(ws.boards),
                "board_ids": [bp.board_id for bp in ws.boards],
                "overlap_warnings": overlap_warnings,
                "status": "created",
            }
        )
    except Exception as exc:
        return err_payload(str(exc), "MB3D_CREATE_ERROR")


# ---------------------------------------------------------------------------
# Tool 2: electronics_mb3d_add_connector
# ---------------------------------------------------------------------------

_add_connector_spec = ToolSpec(
    name="electronics_mb3d_add_connector",
    description=(
        "Declare a mating inter-board connector pair in an existing workspace "
        "definition. Provide the connector name, both board_ids + designators, "
        "pin counts, and a pin_mapping dict ({from_pin: to_pin, ...}). "
        "The tool validates the mapping for pin-count consistency and flags "
        "mismatches (Altium §4.3 / IPC-2581 §7.4.2). "
        "Returns validation results for this connector."
    ),
    input_schema={
        "type": "object",
        "required": [
            "name",
            "from_board",
            "from_designator",
            "from_pin_count",
            "to_board",
            "to_designator",
            "to_pin_count",
            "pin_mapping",
        ],
        "properties": {
            "name": {"type": "string"},
            "from_board": {"type": "string"},
            "from_designator": {"type": "string"},
            "from_pin_count": {"type": "integer"},
            "to_board": {"type": "string"},
            "to_designator": {"type": "string"},
            "to_pin_count": {"type": "integer"},
            "pin_mapping": {
                "type": "object",
                "description": "JSON object: string pin numbers → string pin numbers.",
                "additionalProperties": {"type": "integer"},
            },
            "connector_type": {
                "type": "string",
                "enum": ["board_to_board", "flex_cable", "wire_harness"],
            },
        },
    },
)


@register(_add_connector_spec)
def _handle_add_connector(args: dict[str, Any]) -> str:
    try:
        pin_mapping = {int(k): int(v) for k, v in args["pin_mapping"].items()}

        conn = InterBoardConnector(
            name=str(args["name"]),
            from_board=str(args["from_board"]),
            from_designator=str(args["from_designator"]),
            from_pin_count=int(args["from_pin_count"]),
            to_board=str(args["to_board"]),
            to_designator=str(args["to_designator"]),
            to_pin_count=int(args["to_pin_count"]),
            pin_mapping=pin_mapping,
            connector_type=str(args.get("connector_type", "board_to_board")),
        )

        # Validate just this connector in isolation using a minimal workspace
        dummy_ws = MultiBoardWorkspace(
            workspace_name="_validate",
            boards=[
                BoardPlacement(
                    conn.from_board, "", (0, 0, 0), (0, 0, 0)  # type: ignore[arg-type]
                ),
                BoardPlacement(
                    conn.to_board, "", (200, 0, 0), (0, 0, 0)  # type: ignore[arg-type]
                ),
            ],
            connectors=[conn],
        )
        issues = dummy_ws.validate_connector_mating()

        return ok_payload(
            {
                "connector_name": conn.name,
                "from": f"{conn.from_board}/{conn.from_designator} ({conn.from_pin_count} pins)",
                "to": f"{conn.to_board}/{conn.to_designator} ({conn.to_pin_count} pins)",
                "mapped_pin_count": len(pin_mapping),
                "validation_issues": issues,
                "valid": len(issues) == 0,
            }
        )
    except Exception as exc:
        return err_payload(str(exc), "MB3D_ADD_CONNECTOR_ERROR")


# ---------------------------------------------------------------------------
# Tool 3: electronics_mb3d_validate_workspace
# ---------------------------------------------------------------------------

_validate_spec = ToolSpec(
    name="electronics_mb3d_validate_workspace",
    description=(
        "Validate a complete multi-board workspace: check all connector "
        "mating pairs for pin-count consistency, detect self-loops, "
        "identify boards with no connector declarations, and run a 2-D "
        "bounding-box overlap check. "
        "Accepts the same workspace JSON as electronics_mb3d_create_workspace "
        "plus a 'connectors' list. "
        "Returns a structured report with mating_issues and overlap_warnings."
    ),
    input_schema={
        "type": "object",
        "required": ["workspace_name", "boards", "connectors"],
        "properties": {
            "workspace_name": {"type": "string"},
            "boards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["board_id", "file_path", "position"],
                    "properties": {
                        "board_id": {"type": "string"},
                        "file_path": {"type": "string"},
                        "position": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "rotation_xyz_deg": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "board_width_mm": {"type": "number"},
                        "board_height_mm": {"type": "number"},
                    },
                },
            },
            "connectors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "name",
                        "from_board",
                        "from_designator",
                        "from_pin_count",
                        "to_board",
                        "to_designator",
                        "to_pin_count",
                        "pin_mapping",
                    ],
                },
            },
        },
    },
)


@register(_validate_spec)
def _handle_validate_workspace(args: dict[str, Any]) -> str:
    try:
        ws = _build_workspace(args)
        mating_issues = ws.validate_connector_mating()
        overlap_warnings = ws.check_board_overlaps()
        return ok_payload(
            {
                "workspace_name": ws.workspace_name,
                "board_count": len(ws.boards),
                "connector_count": len(ws.connectors),
                "mating_issues": mating_issues,
                "overlap_warnings": overlap_warnings,
                "valid": len(mating_issues) == 0 and len(overlap_warnings) == 0,
            }
        )
    except Exception as exc:
        return err_payload(str(exc), "MB3D_VALIDATE_ERROR")


# ---------------------------------------------------------------------------
# Tool 4: electronics_mb3d_net_map
# ---------------------------------------------------------------------------

_net_map_spec = ToolSpec(
    name="electronics_mb3d_net_map",
    description=(
        "Compute the cross-board net map for a multi-board workspace. "
        "Walks all connector pin_mappings and resolves global workspace-level "
        "net names from per-board local net names. "
        "Flags floating connector pins, impedance mismatches (Bogatin §11.3: "
        ">10% Z0 delta = warning, >25% = error), and differential pair health "
        "(IPC-2141A §6). "
        "board_net_assignments: {board_id: {designator: {pin_int: net_name}}}. "
        "board_impedances: {board_id: {net_name: Z0_ohm}}."
    ),
    input_schema={
        "type": "object",
        "required": ["workspace_name", "boards", "connectors"],
        "properties": {
            "workspace_name": {"type": "string"},
            "boards": {"type": "array", "items": {"type": "object"}},
            "connectors": {"type": "array", "items": {"type": "object"}},
            "board_net_assignments": {
                "type": "object",
                "description": "Per-board connector pin→net mapping.",
            },
            "board_impedances": {
                "type": "object",
                "description": "Per-board net→Z0 (Ω) mapping.",
            },
        },
    },
)


@register(_net_map_spec)
def _handle_net_map(args: dict[str, Any]) -> str:
    try:
        ws = _build_workspace(args)

        # Re-key board_net_assignments: convert string pin keys to int
        raw_bna = args.get("board_net_assignments") or {}
        bna: dict[str, dict[str, dict[int, str]]] = {}
        for board_id, desig_map in raw_bna.items():
            bna[board_id] = {}
            for desig, pin_map in desig_map.items():
                bna[board_id][desig] = {int(k): str(v) for k, v in pin_map.items()}

        report = compute_workspace_net_map(
            ws,
            board_net_assignments=bna or None,
            board_impedances=args.get("board_impedances"),
        )
        continuity_issues = check_signal_continuity(report)

        return ok_payload(
            {
                "bridge_count": len(report.bridges),
                "bridges": [
                    {
                        "workspace_net": b.workspace_net_name,
                        "board_a": b.board_a,
                        "board_a_net": b.board_a_local_net,
                        "board_b": b.board_b,
                        "board_b_net": b.board_b_local_net,
                        "connector": b.connector_pair_name,
                        "from_pin": b.from_pin,
                        "to_pin": b.to_pin,
                    }
                    for b in report.bridges
                ],
                "floating_nets": [
                    {"board": fboard, "net": fnet}
                    for fboard, fnet in report.floating_nets
                ],
                "impedance_continuity": report.impedance_continuity,
                "diff_pair_continuity": report.diff_pair_continuity,
                "continuity_issues": continuity_issues,
            }
        )
    except Exception as exc:
        return err_payload(str(exc), "MB3D_NET_MAP_ERROR")


# ---------------------------------------------------------------------------
# Tool 5: electronics_mb3d_export_step
# ---------------------------------------------------------------------------

_export_step_spec = ToolSpec(
    name="electronics_mb3d_export_step",
    description=(
        "Export the multi-board assembly as a STEP AP242 file. "
        "Each board is placed at its declared position/rotation in the workspace "
        "coordinate frame (Altium MB3D §5 / STEP AP242 §9.3). "
        "Returns base64-encoded STEP bytes + a 'filename' suggestion. "
        "If pythonOCC is available, solid board geometry is produced; otherwise "
        "a parametric bounding-box STEP is returned (always valid for MCAD import)."
    ),
    input_schema={
        "type": "object",
        "required": ["workspace_name", "boards", "connectors"],
        "properties": {
            "workspace_name": {"type": "string"},
            "boards": {"type": "array", "items": {"type": "object"}},
            "connectors": {"type": "array", "items": {"type": "object"}},
            "enclosure_step_file": {"type": "string"},
        },
    },
)


@register(_export_step_spec)
def _handle_export_step(args: dict[str, Any]) -> str:
    try:
        ws = _build_workspace(args)
        step_bytes = ws.export_assembly_step()
        step_b64 = base64.b64encode(step_bytes).decode("ascii")
        filename = f"{ws.workspace_name.replace(' ', '_')}_assembly.stp"
        return ok_payload(
            {
                "filename": filename,
                "step_b64": step_b64,
                "board_count": len(ws.boards),
                "size_bytes": len(step_bytes),
            }
        )
    except Exception as exc:
        return err_payload(str(exc), "MB3D_EXPORT_STEP_ERROR")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_workspace(args: dict[str, Any]) -> MultiBoardWorkspace:
    """Deserialise a workspace + connectors from LLM tool args dict."""
    placements = []
    for b in args.get("boards", []):
        pos = tuple(float(v) for v in b["position"])  # type: ignore[arg-type]
        rot = tuple(float(v) for v in b.get("rotation_xyz_deg", [0.0, 0.0, 0.0]))  # type: ignore[arg-type]
        placements.append(
            BoardPlacement(
                board_id=str(b["board_id"]),
                file_path=str(b.get("file_path", "")),
                position=pos,  # type: ignore[arg-type]
                rotation_xyz_deg=rot,  # type: ignore[arg-type]
                board_width_mm=float(b.get("board_width_mm", 100.0)),
                board_height_mm=float(b.get("board_height_mm", 80.0)),
            )
        )

    connectors = []
    for c in args.get("connectors", []):
        pin_mapping = {int(k): int(v) for k, v in c.get("pin_mapping", {}).items()}
        connectors.append(
            InterBoardConnector(
                name=str(c["name"]),
                from_board=str(c["from_board"]),
                from_designator=str(c["from_designator"]),
                from_pin_count=int(c["from_pin_count"]),
                to_board=str(c["to_board"]),
                to_designator=str(c["to_designator"]),
                to_pin_count=int(c["to_pin_count"]),
                pin_mapping=pin_mapping,
                connector_type=str(c.get("connector_type", "board_to_board")),
            )
        )

    return MultiBoardWorkspace(
        workspace_name=str(args["workspace_name"]),
        boards=placements,
        connectors=connectors,
        enclosure_step_file=args.get("enclosure_step_file"),
    )


# ---------------------------------------------------------------------------
# TOOLS manifest (for plugin.py tool_modules import path)
# ---------------------------------------------------------------------------

TOOLS = [
    (
        "electronics_mb3d_create_workspace",
        _create_workspace_spec,
        _handle_create_workspace,
    ),
    (
        "electronics_mb3d_add_connector",
        _add_connector_spec,
        _handle_add_connector,
    ),
    (
        "electronics_mb3d_validate_workspace",
        _validate_spec,
        _handle_validate_workspace,
    ),
    (
        "electronics_mb3d_net_map",
        _net_map_spec,
        _handle_net_map,
    ),
    (
        "electronics_mb3d_export_step",
        _export_step_spec,
        _handle_export_step,
    ),
]
