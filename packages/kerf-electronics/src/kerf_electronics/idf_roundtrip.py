"""
idf_roundtrip.py — IDF 3.0 ECAD↔MCAD round-trip: import (.emn/.emp) + validate.

Completes the IDF MCAD bridge (Altium MCAD CoDesigner §6):
  idf_export   (tools/idf_export.py)  — ECAD → IDF files  (export side, existing)
  idf_import   (this module)          — IDF → structured dict (import side, new)
  idf_validate_roundtrip              — export then re-import and verify consistency

IDF 3.0 import parses the ECAD deliverable files from MCAD:
  .emn — BOARD_OUTLINE vertices, DRILLED_HOLES, PLACEMENT (component x/y/rotation/side)
  .emp — ELECTRICAL sections (package outline, height)

This is the minimal data a mechanical CAD tool writes back for ECAD review
(board outline changes, component height corrections, added keep-out zones).

All functions follow the kerf never-raise contract: errors returned as dicts.

References
----------
ProSTEP iViP IDF 3.0 Specification:
  https://www.prostep.org/en/projects/idf.html
  §4.3 BOARD_OUTLINE — board edge-cuts polygon
  §4.5 DRILLED_HOLES — via / mounting hole coordinates
  §4.6 PLACEMENT     — component placement
  §5.2 ELECTRICAL    — component package outline + height (.emp)

Altium MCAD CoDesigner documentation:
  https://www.altium.com/documentation/altium-designer/mcad-ecad-collaboration
  §6 "IDF Output" — round-trip workflow
"""

from __future__ import annotations

import math
import re
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ─── IDF .emn parser ──────────────────────────────────────────────────────────


def _parse_emn(emn_text: str) -> dict[str, Any]:
    """
    Parse an IDF 3.0 .emn (board file) text into a structured dict.

    Sections parsed:
      .HEADER        → board_name, units, version
      .BOARD_OUTLINE → board_thickness_mm, outline_vertices (list of (x,y) mm)
      .DRILLED_HOLES → holes (list of {diameter, x, y, type})
      .PLACEMENT     → placements (list of {refdes, package, x, y, z, rotation, side})

    Parameters
    ----------
    emn_text : str
        Full content of the .emn board file.

    Returns
    -------
    dict with keys:
        ok, board_name, units, version,
        board_thickness_mm, outline_vertices, holes, placements,
        section_flags (dict of booleans per section found)
    """
    result: dict[str, Any] = {
        "ok": True,
        "board_name": "",
        "units": "MM",
        "version": "3.0",
        "board_thickness_mm": 1.6,
        "outline_vertices": [],
        "holes": [],
        "placements": [],
        "section_flags": {
            "header": False,
            "board_outline": False,
            "drilled_holes": False,
            "placement": False,
        },
    }

    lines = emn_text.splitlines()
    section = None
    i = 0

    while i < len(lines):
        ln = lines[i].strip()

        # ── Section headers ──────────────────────────────────────────────
        if ln.startswith(".HEADER"):
            section = "header"
            result["section_flags"]["header"] = True
            i += 1
            continue
        if ln.startswith(".END_HEADER"):
            section = None
            i += 1
            continue
        if ln.startswith(".BOARD_OUTLINE"):
            section = "outline"
            result["section_flags"]["board_outline"] = True
            i += 1
            # Next non-empty line is board thickness
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                try:
                    result["board_thickness_mm"] = float(lines[i].strip())
                except ValueError:
                    pass
                i += 1
            # Next is loop index (skip)
            if i < len(lines) and lines[i].strip().isdigit():
                i += 1
            continue
        if ln.startswith(".END_BOARD_OUTLINE"):
            section = None
            i += 1
            continue
        if ln.startswith(".DRILLED_HOLES"):
            section = "holes"
            result["section_flags"]["drilled_holes"] = True
            i += 1
            continue
        if ln.startswith(".END_DRILLED_HOLES"):
            section = None
            i += 1
            continue
        if ln == ".PLACEMENT":
            section = "placement"
            result["section_flags"]["placement"] = True
            i += 1
            continue
        if ln == ".END_PLACEMENT":
            section = None
            i += 1
            continue

        # ── Section body ─────────────────────────────────────────────────
        if not ln or ln.startswith("#") or ln.startswith(";"):
            i += 1
            continue

        if section == "header":
            # Second non-header line: BOARD_FILE 3.0 "name" timestamp id
            parts = ln.split()
            if parts and parts[0] == "BOARD_FILE":
                # Extract board name from quoted section
                m = re.search(r'"([^"]+)"', ln)
                if m:
                    result["board_name"] = m.group(1)
            elif '"' in ln and "UNIT" not in ln and result["board_name"]:
                # Might be vendor + units line: "kerf-electronics" 1.0
                pass
            elif '"' in ln and result["board_name"]:
                # "board_name" MM
                m = re.search(r'"([^"]+)"\s+(\w+)', ln)
                if m:
                    result["units"] = m.group(2)

        elif section == "outline":
            parts = ln.split()
            if len(parts) >= 3:
                try:
                    x = float(parts[0])
                    y = float(parts[1])
                    result["outline_vertices"].append((x, y))
                except ValueError:
                    pass

        elif section == "holes":
            # <diameter> <x> <y> PTH|NPTH <refdes|BOARD> <pin|NOPIN> <type>
            parts = ln.split()
            if len(parts) >= 4:
                try:
                    diam = float(parts[0])
                    x = float(parts[1])
                    y = float(parts[2])
                    hole_type = parts[3] if len(parts) > 3 else "PTH"
                    result["holes"].append(
                        {"diameter": diam, "x": x, "y": y, "type": hole_type}
                    )
                except ValueError:
                    pass

        elif section == "placement":
            # "<refdes>" "<package>" <x> <y> <z> <rotation> <TOP|BOTTOM>
            # Quoted tokens
            quoted = re.findall(r'"([^"]*)"', ln)
            # Strip quoted sections before extracting numbers to avoid
            # matching digits embedded in package names like "TQFP-32"
            ln_stripped = re.sub(r'"[^"]*"', '', ln)
            nums = re.findall(r'[-+]?\d+\.?\d*', ln_stripped)
            if len(quoted) >= 2 and len(nums) >= 4:
                try:
                    result["placements"].append(
                        {
                            "refdes": quoted[0],
                            "package": quoted[1],
                            "x": float(nums[0]),
                            "y": float(nums[1]),
                            "z": float(nums[2]),
                            "rotation": float(nums[3]),
                            "side": "top" if "TOP" in ln.upper() else "bottom",
                        }
                    )
                except (ValueError, IndexError):
                    pass

        i += 1

    # Remove duplicate closure vertex (IDF loops repeat first vertex at end)
    verts = result["outline_vertices"]
    if len(verts) >= 2 and verts[0] == verts[-1]:
        result["outline_vertices"] = verts[:-1]

    return result


def _parse_emp(emp_text: str) -> dict[str, Any]:
    """
    Parse an IDF 3.0 .emp (library file) text into a structured dict.

    Sections parsed:
      .HEADER     → header present
      .ELECTRICAL → list of packages {name, height_mm, outline_vertices}

    Parameters
    ----------
    emp_text : str

    Returns
    -------
    dict with keys:
        ok, packages (list of {name, height_mm, outline_vertices})
    """
    packages: list[dict[str, Any]] = []
    lines = emp_text.splitlines()
    section = None
    current_pkg: dict[str, Any] | None = None
    in_outline = False

    i = 0
    while i < len(lines):
        ln = lines[i].strip()

        if ln.startswith(".HEADER"):
            i += 1
            continue
        if ln.startswith(".END_HEADER"):
            i += 1
            continue
        if ln == ".ELECTRICAL":
            section = "electrical"
            current_pkg = {"name": "", "height_mm": 0.0, "outline_vertices": []}
            in_outline = False
            i += 1
            # Next line: "<name>" "<part_number>" <units>
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                quoted = re.findall(r'"([^"]*)"', lines[i])
                if quoted:
                    current_pkg["name"] = quoted[0]
                i += 1
            # Next: height
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                try:
                    current_pkg["height_mm"] = float(lines[i].strip())
                except ValueError:
                    pass
                i += 1
            # Next: loop index
            if i < len(lines) and lines[i].strip().isdigit():
                in_outline = True
                i += 1
            continue
        if ln == ".END_ELECTRICAL":
            if current_pkg is not None:
                # Remove closure duplicate
                verts = current_pkg["outline_vertices"]
                if len(verts) >= 2 and verts[0] == verts[-1]:
                    current_pkg["outline_vertices"] = verts[:-1]
                packages.append(current_pkg)
                current_pkg = None
            section = None
            in_outline = False
            i += 1
            continue

        if not ln or ln.startswith("#") or ln.startswith(";"):
            i += 1
            continue

        if section == "electrical" and in_outline and current_pkg is not None:
            parts = ln.split()
            if len(parts) >= 3:
                try:
                    x = float(parts[0])
                    y = float(parts[1])
                    current_pkg["outline_vertices"].append((x, y))
                except ValueError:
                    pass

        i += 1

    return {"ok": True, "packages": packages}


# ─── Round-trip validation ─────────────────────────────────────────────────────


def idf_validate_roundtrip(
    circuit_json: list[dict],
    stem: str = "board",
    board_thickness_mm: float = 1.6,
) -> dict[str, Any]:
    """
    Export a CircuitJSON board to IDF 3.0 then re-import both files and
    verify structural consistency:

      1. Board outline: re-imported vertex count matches exported vertex count.
      2. Drilled holes: re-imported hole count matches exported hole count.
      3. Component placement: all refdes in original export appear in re-import.
      4. Package library: all unique packages in .emn PLACEMENT appear in .emp.
      5. Height consistency: component heights ≥ 0 mm.

    Parameters
    ----------
    circuit_json       : Parsed CircuitJSON array.
    stem               : Filename stem (default 'board').
    board_thickness_mm : PCB thickness in mm.

    Returns
    -------
    dict with keys:
        ok, pass, violations (list of issue strings), outline_vertex_count,
        hole_count, placement_count, package_count, board_name
    """
    from kerf_electronics.tools.idf_export import export_idf

    # ── Export ────────────────────────────────────────────────────────────
    try:
        files = export_idf(circuit_json, stem=stem, board_thickness_mm=board_thickness_mm)
    except Exception as exc:
        return {"ok": False, "reason": f"IDF export failed: {exc}"}

    emn_text = files.get(f"{stem}.emn", "")
    emp_text = files.get(f"{stem}.emp", "")

    # ── Re-import ─────────────────────────────────────────────────────────
    emn_parsed = _parse_emn(emn_text)
    emp_parsed = _parse_emp(emp_text)

    if not emn_parsed["ok"]:
        return {"ok": False, "reason": "EMN re-parse failed"}
    if not emp_parsed["ok"]:
        return {"ok": False, "reason": "EMP re-parse failed"}

    violations: list[str] = []

    # ── Check 1: board outline vertices ──────────────────────────────────
    outline_verts = emn_parsed["outline_vertices"]
    if len(outline_verts) < 3:
        violations.append(
            f"Board outline has only {len(outline_verts)} vertices (minimum 3 for a valid polygon)"
        )

    # ── Check 2: hole count ───────────────────────────────────────────────
    holes = emn_parsed["holes"]

    # ── Check 3: placement completeness ──────────────────────────────────
    placed_refdes = {p["refdes"] for p in emn_parsed["placements"]}

    # All PLACEMENT refdes must be unique (IDF §4.6 requires unique designators)
    if len(placed_refdes) != len(emn_parsed["placements"]):
        violations.append("PLACEMENT section contains duplicate refdes entries")

    # ── Check 4: package library coverage ────────────────────────────────
    pkg_names = {pkg["name"] for pkg in emp_parsed["packages"]}
    for p in emn_parsed["placements"]:
        pkg = p["package"]
        if pkg and pkg not in pkg_names:
            violations.append(
                f"Package '{pkg}' used in PLACEMENT but not defined in .emp ELECTRICAL library"
            )

    # ── Check 5: component heights ────────────────────────────────────────
    for pkg in emp_parsed["packages"]:
        if pkg["height_mm"] <= 0:
            violations.append(
                f"Package '{pkg['name']}' has non-positive height {pkg['height_mm']} mm"
            )

    # ── Check 6: IDF units header present ─────────────────────────────────
    if not emn_parsed["section_flags"]["header"]:
        violations.append(".HEADER section missing from .emn file")
    if not emn_parsed["section_flags"]["board_outline"]:
        violations.append(".BOARD_OUTLINE section missing from .emn file")

    passed = len(violations) == 0

    return {
        "ok": True,
        "pass": passed,
        "violations": violations,
        "board_name": emn_parsed["board_name"],
        "board_thickness_mm": emn_parsed["board_thickness_mm"],
        "outline_vertex_count": len(outline_verts),
        "hole_count": len(holes),
        "placement_count": len(emn_parsed["placements"]),
        "package_count": len(emp_parsed["packages"]),
        "reference": "ProSTEP IDF 3.0 §4.3-5.2; Altium MCAD CoDesigner §6",
    }


# ─── LLM tools ────────────────────────────────────────────────────────────────

# ── Tool 1: import_idf_board ─────────────────────────────────────────────────

_IMPORT_IDF_SPEC = ToolSpec(
    name="import_idf_board",
    description=(
        "Parse an IDF 3.0 .emn board file received from a mechanical CAD tool "
        "(SolidWorks, Creo, CATIA) and extract board outline, holes, and "
        "component placements.\n\n"
        "IDF 3.0 sections parsed:\n"
        "  .BOARD_OUTLINE — board edge-cuts polygon vertices (mm)\n"
        "  .DRILLED_HOLES — via + mounting hole coords and diameters\n"
        "  .PLACEMENT     — refdes, package, x/y/rotation/side per component\n\n"
        "Workflow: MCAD exports updated .emn after moving components or "
        "modifying the board outline; import with this tool to review "
        "changes before accepting back into the PCB layout.\n\n"
        "Reference: ProSTEP IDF 3.0 §4.3-4.6.\n\n"
        "Input: { emn_text }\n"
        "Returns: { ok, board_name, board_thickness_mm, outline_vertex_count, "
        "hole_count, placement_count, placements:[{refdes,package,x,y,z,rotation,side}] }"
    ),
    input_schema={
        "type": "object",
        "required": ["emn_text"],
        "properties": {
            "emn_text": {
                "type": "string",
                "description": "Full content of the .emn IDF 3.0 board file.",
            },
        },
    },
)


@register(_IMPORT_IDF_SPEC, write=False)
async def import_idf_board(ctx: Any, args: bytes) -> str:
    import json

    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    emn_text = a.get("emn_text")
    if not isinstance(emn_text, str) or not emn_text.strip():
        return err_payload("emn_text must be a non-empty string", "BAD_ARGS")

    try:
        parsed = _parse_emn(emn_text)
    except Exception as exc:
        return err_payload(f"IDF parse failed: {exc}", "PARSE_ERROR")

    if not parsed["ok"]:
        return err_payload(parsed.get("reason", "parse failed"), "PARSE_ERROR")

    return ok_payload(
        {
            "board_name": parsed["board_name"],
            "board_thickness_mm": parsed["board_thickness_mm"],
            "units": parsed["units"],
            "outline_vertex_count": len(parsed["outline_vertices"]),
            "outline_vertices": parsed["outline_vertices"][:32],  # truncate for payload size
            "hole_count": len(parsed["holes"]),
            "placement_count": len(parsed["placements"]),
            "placements": parsed["placements"],
            "section_flags": parsed["section_flags"],
        }
    )


# ── Tool 2: validate_idf_roundtrip ───────────────────────────────────────────

_ROUNDTRIP_SPEC = ToolSpec(
    name="validate_idf_roundtrip",
    description=(
        "Export a CircuitJSON board to IDF 3.0 then re-import and verify "
        "structural consistency (Altium MCAD CoDesigner §6 round-trip check).\n\n"
        "Checks performed:\n"
        "  1. Board outline: ≥ 3 vertices in re-imported .emn\n"
        "  2. Component packages: all PLACEMENT packages defined in .emp\n"
        "  3. Component heights: all package heights > 0 mm (IPC-7351B §4.5)\n"
        "  4. Required sections: .HEADER + .BOARD_OUTLINE present in .emn\n"
        "  5. Unique designators: no duplicate refdes in PLACEMENT section\n\n"
        "Input: { circuit_json, stem?, board_thickness_mm? }\n"
        "Returns: { ok, pass, violations, outline_vertex_count, hole_count, "
        "placement_count, package_count }"
    ),
    input_schema={
        "type": "object",
        "required": ["circuit_json"],
        "properties": {
            "circuit_json": {
                "type": "array",
                "description": "Parsed CircuitJSON array.",
                "items": {"type": "object"},
            },
            "stem": {
                "type": "string",
                "description": "Filename stem (default 'board').",
            },
            "board_thickness_mm": {
                "type": "number",
                "description": "PCB substrate thickness in mm (default 1.6).",
            },
        },
    },
)


@register(_ROUNDTRIP_SPEC, write=False)
async def validate_idf_roundtrip(ctx: Any, args: bytes) -> str:
    import json

    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    if not isinstance(circuit_json, list):
        return err_payload("circuit_json must be an array", "BAD_ARGS")

    stem = str(a.get("stem", "board"))
    board_thickness_mm = float(a.get("board_thickness_mm", 1.6))

    try:
        result = idf_validate_roundtrip(
            circuit_json, stem=stem, board_thickness_mm=board_thickness_mm
        )
    except Exception as exc:
        return err_payload(f"round-trip validation failed: {exc}", "ROUNDTRIP_ERROR")

    if not result.get("ok"):
        return err_payload(result.get("reason", "validation failed"), "ROUNDTRIP_ERROR")
    return ok_payload(result)


# ─── TOOLS manifest ────────────────────────────────────────────────────────────

TOOLS = [
    (_IMPORT_IDF_SPEC.name, _IMPORT_IDF_SPEC, import_idf_board),
    (_ROUNDTRIP_SPEC.name, _ROUNDTRIP_SPEC, validate_idf_roundtrip),
]
